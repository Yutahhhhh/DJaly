from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select
from infra.database.connection import get_session
from domain.models.lyrics import Lyrics
from domain.models.track import Track
from api.schemas.lyrics import LyricsRead
import re
from typing import List, Optional

router = APIRouter()

# LRC タイムタグ ([mm:ss.xx]) のみを除去する (歌詞中の [bracket] 表現を巻き込まない)
LRC_TIME_TAG_RE = re.compile(r'\[\d{1,2}:\d{2}(?:\.\d+)?\]')

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
                clean_line = LRC_TIME_TAG_RE.sub('', line).strip()

                # 前後のコンテキストを含めたスニペットを作成
                start = max(0, i - 1)
                end = min(len(lines), i + 2)
                snippet = [LRC_TIME_TAG_RE.sub('', l).strip() for l in lines[start:end]]
                
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
