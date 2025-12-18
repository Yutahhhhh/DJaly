from fastapi import APIRouter, HTTPException, Depends, Body
from fastapi.responses import FileResponse
from sqlmodel import Session, select
from db import get_session
from models import Track, TrackAnalysis
from schemas.common import ListPathRequest, MetadataUpdate
from utils.filesystem import resolve_path
from utils.metadata import update_file_metadata
from utils.llm import generate_text
from services.filesystem import FilesystemService
import requests
import urllib.parse
import base64
import json
import re

router = APIRouter()
fs_service = FilesystemService()

def clean_title_for_search(title: str) -> str:
    """タイトルから (Remix) や [feat.] などの付加情報を削除する"""
    return re.sub(r'\s*[\(\[].*?[\)\]]', '', title).strip()

def fetch_lyrics_from_api(artist: str, title: str) -> str | None:
    """外部API (Lrclib -> lyrics.ovh) を使用して歌詞を取得する"""
    
    # 1. Lrclib (高品質・高確率)
    try:
        # Lrclibは正確な検索が得意
        params = {"artist_name": artist, "track_name": title}
        resp = requests.get("https://lrclib.net/api/get", params=params, timeout=3)
        if resp.status_code == 200:
            data = resp.json()
            if data.get("plainLyrics"):
                return data.get("plainLyrics")
        
        # 見つからない場合、クリーニングして再試行
        cleaned_title = clean_title_for_search(title)
        if cleaned_title != title:
            params["track_name"] = cleaned_title
            resp = requests.get("https://lrclib.net/api/get", params=params, timeout=3)
            if resp.status_code == 200:
                data = resp.json()
                if data.get("plainLyrics"):
                    return data.get("plainLyrics")
    except Exception as e:
        print(f"Lrclib API Error: {e}")

    # 2. lyrics.ovh (フォールバック)
    try:
        url = f"https://api.lyrics.ovh/v1/{artist}/{title}"
        resp = requests.get(url, timeout=3)
        if resp.status_code == 200:
            data = resp.json()
            if data.get("lyrics"):
                return data.get("lyrics")
        
        cleaned_title = clean_title_for_search(title)
        if cleaned_title != title:
            url = f"https://api.lyrics.ovh/v1/{artist}/{cleaned_title}"
            resp = requests.get(url, timeout=3)
            if resp.status_code == 200:
                data = resp.json()
                if data.get("lyrics"):
                    return data.get("lyrics")
    except Exception as e:
        print(f"Lyrics.ovh API Error: {e}")
    
    return None

@router.get("/api/stream")
def stream_track(path: str):
    """オーディオファイルをストリーム再生用に提供する"""
    resolved_path = resolve_path(path)
    if not resolved_path:
        raise HTTPException(status_code=404, detail="File not found")
    
    return FileResponse(resolved_path)

@router.get("/api/metadata")
def get_track_metadata(track_id: int, session: Session = Depends(get_session)):
    """拡張メタデータを取得する。DBの解析データと物理ファイルのタグ情報を統合して返す"""
    metadata = fs_service.get_track_metadata(session, track_id)
    if not metadata:
        raise HTTPException(status_code=404, detail="Track not found or file missing")
    return metadata

@router.post("/api/fs/list")
def list_directory(req: ListPathRequest, session: Session = Depends(get_session)):
    """指定されたパス直下のファイル/フォルダ一覧を返す。解析済みステータスとフィルタリングを含む"""
    result = fs_service.list_directory(session, req.path)
    
    if result is None:
        raise HTTPException(status_code=404, detail="Path not found")

    if not req.hide_analyzed:
        return result

    return [item for item in result if not (not item['is_dir'] and item.get('is_analyzed'))]

@router.patch("/api/metadata/update")
def update_metadata_content(
    update: MetadataUpdate,
    session: Session = Depends(get_session)
):
    """物理ファイルのタグ情報（歌詞・アートワーク）を更新する"""
    track = session.get(Track, update.track_id)
    if not track or not track.filepath:
        raise HTTPException(status_code=404, detail="Track not found")
    
    # 1. 物理ファイルの更新 (歌詞, アートワーク)
    if update.lyrics is not None or update.artwork_data is not None:
        success = update_file_metadata(track.filepath, lyrics=update.lyrics, artwork_b64=update.artwork_data)
        if not success:
            raise HTTPException(status_code=500, detail="Failed to write metadata to file")
    
    return {"status": "success"}

@router.post("/api/metadata/fetch-lyrics")
def fetch_lyrics(
    track_id: int = Body(..., embed=True),
    session: Session = Depends(get_session)
):
    """歌詞を検索・取得する (APIのみ使用 - LLM生成は行わない)"""
    track = session.get(Track, track_id)
    if not track:
        raise HTTPException(status_code=404, detail="Track not found")
    
    # 外部APIのみを使用し、LLMによる生成（ハルシネーション）を防ぐ
    api_lyrics = fetch_lyrics_from_api(track.artist, track.title)
    if api_lyrics:
        return {"lyrics": api_lyrics}

    # 見つからない場合は空文字を返す
    return {"lyrics": ""}

@router.post("/api/metadata/fetch-artwork-info")
def fetch_artwork_info(
    track_id: int = Body(..., embed=True),
    session: Session = Depends(get_session)
):
    """iTunes APIを使用してアートワーク画像を検索・取得し、Base64で返す"""
    track = session.get(Track, track_id)
    if not track:
        raise HTTPException(status_code=404, detail="Track not found")
    
    # 検索クエリ
    query = f"{track.artist} {track.album}" if track.album else f"{track.artist} {track.title}"
    
    try:
        # iTunes Search API
        encoded_query = urllib.parse.quote(query)
        url = f"https://itunes.apple.com/search?term={encoded_query}&media=music&entity=album&limit=1"
        
        response = requests.get(url, timeout=10)
        data = response.json()
        
        if data["resultCount"] > 0:
            result = data["results"][0]
            artwork_url = result.get("artworkUrl100")
            if artwork_url:
                # 高画質化 (100x100 -> 1000x1000)
                high_res_url = artwork_url.replace("100x100bb", "1000x1000bb")
                
                # 画像ダウンロード
                img_res = requests.get(high_res_url, timeout=10)
                if img_res.status_code == 200:
                    b64_data = base64.b64encode(img_res.content).decode('utf-8')
                    # フロントエンドでそのまま使える形式で返す
                    return {"info": f"data:image/jpeg;base64,{b64_data}"}
        
        return {"info": ""}
        
    except Exception as e:
        print(f"Artwork fetch failed: {e}")
        return {"info": ""}