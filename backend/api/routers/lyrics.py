from fastapi import APIRouter, Depends, HTTPException, Body
from sqlmodel import Session, select, func
from infra.database.connection import get_session
from domain.models.lyrics import Lyrics
from domain.models.track import Track
from api.schemas.lyrics import LyricsRead
import hashlib
import json
import re
from datetime import datetime
from typing import List, Dict, Any, Optional
from utils.llm import generate_text, is_llm_error

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

@router.post("/api/tracks/{track_id}/lyrics/analyze")
def analyze_lyrics(track_id: int, force: bool = False, session: Session = Depends(get_session)):
    """
    LLMを使用して歌詞から『DJワードプレイ用』のキーワードを高度に抽出。
    抽出結果は歌詞の内容ハッシュ付きで永続キャッシュし、2回目以降は即時返却する。
    """
    lyrics_obj = session.get(Lyrics, track_id)
    if not lyrics_obj or not lyrics_obj.content:
        raise HTTPException(status_code=404, detail="Lyrics not found")

    content_hash = hashlib.sha256(lyrics_obj.content.encode("utf-8")).hexdigest()

    # キャッシュヒット時は LLM を呼ばずに返す
    if (
        not force
        and lyrics_obj.keywords_json
        and lyrics_obj.keywords_content_hash == content_hash
    ):
        try:
            return json.loads(lyrics_obj.keywords_json)
        except Exception:
            pass  # 壊れたキャッシュは再生成

    # LRC タイムタグを除去してから LLM に渡す (実質的な歌詞量を確保)
    clean_content = LRC_TIME_TAG_RE.sub('', lyrics_obj.content)[:3000]

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
    {clean_content}
    """

    try:
        raw_res = generate_text(session, prompt, json_mode=True, temperature=0.3)
        if is_llm_error(raw_res):
            keywords = []
        else:
            # JSON部分の抽出
            match = re.search(r'\{.*\}', raw_res, re.DOTALL)
            data = json.loads(match.group(0)) if match else {"keywords": []}
            keywords = data.get("keywords", [])
    except Exception:
        keywords = []

    results = []
    seen = set()

    for kw in keywords:
        if not isinstance(kw, str):
            continue
        kw_clean = kw.strip().lower()
        if not kw_clean or len(kw_clean) < 3 or kw_clean in seen:
            continue

        # 不要な一般語をフィルタリング（ストップワード）
        if kw_clean in ["baby", "love", "night", "wanna", "gotta", "know", "like"]:
            continue

        seen.add(kw_clean)

        # 他の曲で見つかるかを SQL でカウント (全歌詞のメモリロードを回避)
        count = session.exec(
            select(func.count(Lyrics.track_id)).where(
                Lyrics.track_id != track_id,
                Lyrics.content.ilike(f"%{kw_clean}%")
            )
        ).one()
        if isinstance(count, tuple):
            count = count[0]

        if count and count > 0:
            results.append({
                "keyword": kw,
                "count": int(count),
                "importance": 1.0 # 今後、フックなら高くする等の調整が可能
            })

    # 見つかった数が多い順（＝繋ぎ先の候補が多い順）にソート
    sorted_results = sorted(results, key=lambda x: x["count"], reverse=True)

    # キーワードが取れた場合のみキャッシュ保存 (LLM 失敗時の空結果を固定化しない)
    if sorted_results:
        lyrics_obj.keywords_json = json.dumps(sorted_results, ensure_ascii=False)
        lyrics_obj.keywords_content_hash = content_hash
        lyrics_obj.updated_at = datetime.now()
        session.add(lyrics_obj)
        session.commit()

    return sorted_results

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