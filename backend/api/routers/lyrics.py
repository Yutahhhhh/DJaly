from fastapi import APIRouter, Depends, HTTPException, Body
from sqlmodel import Session, select
from infra.database.connection import get_session
from domain.models.lyrics import Lyrics
from domain.models.track import Track
from api.schemas.lyrics import LyricsRead
import json
import re
from typing import List, Dict, Any, Optional
from utils.llm import generate_text

router = APIRouter()

def parse_lrc_timestamp(line: str) -> Optional[float]:
    """LRCのタイムスタンプ [mm:ss.xx] を秒数に変換"""
    match = re.search(r'\[(\d+):(\d+(?:\.\d+)?)\]', line)
    if match:
        minutes = int(match.group(1))
        seconds = float(match.group(2))
        return minutes * 60 + seconds
    return None

@router.get("/api/tracks/{track_id}/lyrics", response_model=LyricsRead)
def get_lyrics(track_id: int, session: Session = Depends(get_session)):
    lyrics = session.get(Lyrics, track_id)
    if not lyrics:
        raise HTTPException(status_code=404, detail="Lyrics not found")
    return lyrics

@router.post("/api/tracks/{track_id}/lyrics/analyze")
def analyze_lyrics(track_id: int, session: Session = Depends(get_session)):
    """
    LLMを使用して歌詞から『DJワードプレイ用』のキーワードを高度に抽出
    """
    lyrics_obj = session.get(Lyrics, track_id)
    if not lyrics_obj or not lyrics_obj.content:
        raise HTTPException(status_code=404, detail="Lyrics not found")

    # 単なるキーワードではなく「繋ぎの文脈」を意識させる
    prompt = f"""
    Analyze the following song lyrics for a professional DJ set.
    Identify and extract "Linkable Phrases" that would make for clever wordplay transitions.

    Categories to extract:
    1. Hook Phrases: Signature lines or catchy repetitive phrases.
    2. Names/Places: Proper nouns like cities, artists, or people.
    3. Thematic Objects: Specific vivid nouns (e.g., "Champagne", "Cocaine", "Midnight", "Telephone").
    4. Action/Mood: Dominant verbs or emotional states.

    Rules:
    - Avoid common filler words (I, you, me, the, baby, yeah).
    - Phrases should be 1-3 words.
    - Return ONLY a JSON object: {{"keywords": ["phrase1", "phrase2", ...]}}

    Lyrics:
    {lyrics_obj.content[:2000]}
    """

    try:
        raw_res = generate_text(session, prompt)
        # JSON部分の抽出
        match = re.search(r'\{.*\}', raw_res, re.DOTALL)
        data = json.loads(match.group(0)) if match else {"keywords": []}
        keywords = data.get("keywords", [])
    except Exception:
        keywords = []

    # 全歌詞をメモリに読み込んで集計（DuckDBなら数千曲程度ならilikeでも高速）
    all_lyrics_stmt = select(Lyrics.track_id, Lyrics.content).where(Lyrics.track_id != track_id)
    all_lyrics = session.exec(all_lyrics_stmt).all()
    
    results = []
    seen = set()
    
    for kw in keywords:
        kw_clean = kw.strip().lower()
        if not kw_clean or len(kw_clean) < 3 or kw_clean in seen:
            continue
        
        # 不要な一般語をフィルタリング（ストップワード）
        if kw_clean in ["baby", "love", "night", "wanna", "gotta", "know", "like"]:
            continue

        seen.add(kw_clean)
        
        # 他の曲で見つかるかカウント
        count = sum(1 for _, content in all_lyrics if content and kw_clean in content.lower())
        
        if count > 0:
            results.append({
                "keyword": kw, 
                "count": count,
                "importance": 1.0 # 今後、フックなら高くする等の調整が可能
            })

    # 見つかった数が多い順（＝繋ぎ先の候補が多い順）にソート
    return sorted(results, key=lambda x: x["count"], reverse=True)

@router.get("/api/lyrics/search")
def search_lyrics(q: str, exclude_track_id: Optional[int] = None, session: Session = Depends(get_session)):
    """
    キーワードで歌詞を検索。 ilike マッチングとスニペット生成。
    """
    if not q or len(q) < 3: return []

    statement = (
        select(Lyrics, Track)
        .join(Track, Lyrics.track_id == Track.id)
        .where(Lyrics.content.ilike(f"%{q}%"))
    )
    if exclude_track_id:
        statement = statement.where(Track.id != exclude_track_id)
        
    db_results = session.exec(statement).all()
    
    response = []
    for lyrics_obj, track in db_results:
        lines = lyrics_obj.content.split('\n')
        
        for i, line in enumerate(lines):
            # 検索語が含まれている行を探す
            if q.lower() in line.lower():
                ts = parse_lrc_timestamp(line)
                clean_line = re.sub(r'\[.*\]', '', line).strip()
                
                # 前後のコンテキストを含めたスニペットを作成
                start = max(0, i - 1)
                end = min(len(lines), i + 2)
                snippet = [re.sub(r'\[.*\]', '', l).strip() for l in lines[start:end]]
                
                track_data = track.model_dump()
                track_data["has_lyrics"] = True
                
                response.append({
                    "track": track_data,
                    "snippet": snippet,
                    "timestamp": ts,
                    "matched_text": clean_line
                })
                # 1曲につき1箇所のヒットに限定（ノイズ低減）
                break
                
    return response