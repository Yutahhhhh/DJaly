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
    """LRCのタイムスタンプ [mm:ss.xx] または [mm:ss] を秒数に変換"""
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
    LLMを使用して歌詞からキーワードを抽出し、他曲での出現回数をカウントして返す。
    単語とフレーズを「Keywords」として統合。
    """
    lyrics_obj = session.get(Lyrics, track_id)
    if not lyrics_obj or not lyrics_obj.content:
        raise HTTPException(status_code=404, detail="Lyrics not found")

    # LLM Prompt - より細かく、DJ的な視点で抽出
    prompt = f"""
    Analyze the following song lyrics and extract impactful keywords and short phrases (2-4 words) 
    that a DJ could use for lyrical connections or wordplay.
    Focus on:
    - Iconic objects/places
    - Strong emotions or actions
    - Catchy hooks
    
    Return ONLY a JSON array of strings: ["keyword1", "phrase 1", ...]
    
    Lyrics:
    {lyrics_obj.content[:1500]}
    """

    try:
        raw_res = generate_text(session, prompt)
        match = re.search(r'\[.*\]', raw_res, re.DOTALL)
        keywords = json.loads(match.group(0)) if match else []
    except Exception as e:
        print(f"LLM extraction failed: {e}")
        keywords = []

    # 全曲の歌詞をロードして出現回数を計算 (本来はFTS等を使うべきだがDuckDB+メモリで対応)
    all_lyrics = session.exec(select(Lyrics.track_id, Lyrics.content)).all()
    
    results = []
    seen = set()
    for kw in keywords:
        kw_lower = kw.lower().strip()
        if not kw_lower or kw_lower in seen: continue
        seen.add(kw_lower)
        
        count = 0
        for other_id, other_content in all_lyrics:
            if other_id == track_id: continue
            if other_content and kw_lower in other_content.lower():
                count += 1
        
        if count > 0:
            results.append({"keyword": kw, "count": count})

    return sorted(results, key=lambda x: x["count"], reverse=True)

@router.get("/api/lyrics/search")
def search_lyrics(q: str, exclude_track_id: Optional[int] = None, session: Session = Depends(get_session)):
    """キーワードで歌詞を検索し、スニペットとタイムスタンプを返す"""
    if not q or len(q) < 2: return []

    statement = select(Lyrics, Track).join(Track).where(Lyrics.content.ilike(f"%{q}%"))
    if exclude_track_id:
        statement = statement.where(Track.id != exclude_track_id)
        
    db_results = session.exec(statement).all()
    
    response = []
    for lyrics_obj, track in db_results:
        lines = lyrics_obj.content.split('\n')
        for i, line in enumerate(lines):
            if q.lower() in line.lower():
                # タイムスタンプ取得
                ts = parse_lrc_timestamp(line)
                clean_line = re.sub(r'\[.*\]', '', line).strip()
                
                # 前後の文脈
                start = max(0, i - 1)
                end = min(len(lines), i + 2)
                snippet = [re.sub(r'\[.*\]', '', l).strip() for l in lines[start:end]]
                
                response.append({
                    "track": track,
                    "snippet": snippet,
                    "timestamp": ts,
                    "matched_text": clean_line
                })
                break
                
    return response