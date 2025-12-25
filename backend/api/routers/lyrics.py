from fastapi import APIRouter, Depends, HTTPException, Body
from sqlmodel import Session, select, func
from infra.database.connection import get_session
from domain.models.lyrics import Lyrics
from domain.models.track import Track
from api.schemas.lyrics import LyricsRead, LyricsUpdate
from datetime import datetime
from typing import List, Dict, Any, Optional
from utils.llm import generate_text, get_llm_config
import json
import re

router = APIRouter()

@router.get("/api/tracks/{track_id}/lyrics", response_model=LyricsRead)
def get_lyrics(
    track_id: int,
    session: Session = Depends(get_session)
):
    lyrics = session.get(Lyrics, track_id)
    if not lyrics:
        raise HTTPException(status_code=404, detail="Lyrics not found")
    return lyrics

@router.put("/api/tracks/{track_id}/lyrics", response_model=LyricsRead)
def update_lyrics(
    track_id: int,
    update: LyricsUpdate,
    session: Session = Depends(get_session)
):
    lyrics = session.get(Lyrics, track_id)
    if not lyrics:
        lyrics = Lyrics(track_id=track_id)
        session.add(lyrics)
    
    if update.content is not None:
        lyrics.content = update.content
    if update.source is not None:
        lyrics.source = update.source
    if update.language is not None:
        lyrics.language = update.language
    
    lyrics.updated_at = datetime.now()
    session.add(lyrics)
    session.commit()
    session.refresh(lyrics)
    return lyrics

@router.get("/api/lyrics/search")
def search_lyrics(
    q: str,
    exclude_track_id: Optional[int] = None,
    session: Session = Depends(get_session)
):
    """
    Search lyrics and return matching tracks with snippets.
    """
    if not q or len(q) < 2:
        return []
        
    # Simple LIKE search for now. 
    # In production with many lyrics, FTS (Full Text Search) would be better.
    statement = select(Lyrics, Track).join(Track).where(Lyrics.content.like(f"%{q}%"))
    
    if exclude_track_id:
        statement = statement.where(Track.id != exclude_track_id)
        
    results = session.exec(statement).all()
    
    response = []
    for lyrics, track in results:
        # Extract snippet
        lines = lyrics.content.split('\n')
        snippet = []
        for i, line in enumerate(lines):
            if q.lower() in line.lower():
                # Get context: 1 line before, current line, 1 line after
                start = max(0, i - 1)
                end = min(len(lines), i + 2)
                snippet = lines[start:end]
                break
        
        response.append({
            "track": track,
            "snippet": snippet,
            "match_line": i if 'i' in locals() else 0
        })
        
    return response


def _extract_keywords_internal(text: str, session: Session) -> Dict[str, List[str]]:
    provider, model_name, api_key, ollama_host = get_llm_config(session)
    
    prompt = f"""
    Analyze the song lyrics below and extract keywords/phrases suitable for DJ wordplay transitions.
    Think like a DJ who wants to mix tracks based on lyrical connections.
    
    Extract two categories:
    
    1. "words": Single words for connecting tracks.
       Find impactful words. Categories include (but are not limited to):
       - Strong Nouns, Places, Names, or Objects (e.g., "Tokyo", "Gold", "World").
       - Antonyms, Pairs, or Opposites (e.g., "Day", "Night", "Love", "Hate").
       - Numbers, Colors, Elements, or Seasons.
       - Interjections, Hype words, or Onomatopoeia (e.g., "Yeah", "Hey", "Boom", "Baby").
       - Homophones or words with interesting sounds.
       (Exclude common stop words like "the", "a", "is" unless they are part of a significant hook)
       
    2. "phrases": Short, catchy phrases (2-6 words).
       - Hooks, Punchlines, or Repeated lines.
       - Call & Response lines.
       - Iconic lyrics.
    
    Return ONLY a valid JSON object with this structure:
    {{
      "words": ["word1", "word2", ...],
      "phrases": ["phrase1", "phrase2", ...]
    }}
    
    Lyrics:
    {text[:1500]}... (truncated)
    """
    
    try:
        # generate_text signature: (session: Session, prompt: str, model_name: Optional[str] = None) -> str
        # The previous call was passing provider, api_key etc which are now handled internally by generate_text using session
        response = generate_text(
            session=session,
            prompt=prompt
        )
        
        # Find JSON object in the response
        match = re.search(r'\{.*\}', response, re.DOTALL)
        if match:
            json_str = match.group(0)
            data = json.loads(json_str)
            return {
                "words": data.get("words", []),
                "phrases": data.get("phrases", [])
            }
        else:
            return {"words": [], "phrases": []}
            
    except Exception as e:
        print(f"Error extracting keywords: {e}")
        return {"words": [], "phrases": []}

@router.post("/api/lyrics/extract-keywords")
def extract_keywords(
    text: str = Body(..., embed=True),
    session: Session = Depends(get_session)
):
    """
    Extract catchy keywords/phrases from lyrics using Ollama.
    """
    return _extract_keywords_internal(text, session)

@router.post("/api/tracks/{track_id}/lyrics/analyze")
def analyze_lyrics(
    track_id: int,
    session: Session = Depends(get_session)
):
    """
    Analyze lyrics for a track and return keywords with match counts in other tracks.
    Returns { "words": [...], "phrases": [...] }
    """
    lyrics = session.get(Lyrics, track_id)
    if not lyrics:
        raise HTTPException(status_code=404, detail="Lyrics not found")
        
    # 1. Extract Words and Phrases using LLM
    extracted = _extract_keywords_internal(lyrics.content, session)
    
    # 2. Get all other lyrics for frequency analysis
    # We fetch ID and Content to avoid fetching full objects
    other_lyrics_rows = session.exec(
        select(Lyrics.content)
        .where(Lyrics.track_id != track_id)
    ).all()
    
    # Pre-process other lyrics for faster searching (lowercase)
    # In a real production DB, we would use Full Text Search (FTS) or an Inverted Index.
    other_lyrics_lower = [l.lower() for l in other_lyrics_rows if l]

    def count_matches(items: List[str]) -> List[Dict[str, Any]]:
        results = []
        seen = set()
        
        for item in items:
            if not item or item.lower() in seen:
                continue
            seen.add(item.lower())
            
            count = 0
            item_lower = item.lower()
            
            for content in other_lyrics_lower:
                # For words, we want word boundary matching to avoid partial matches (e.g. "cat" in "catch")
                # For phrases, simple substring match is usually fine
                if " " not in item: # It's a word
                     # Simple boundary check: space before/after or start/end of string
                     # This is a lightweight approximation of regex \b
                     if item_lower in content:
                         count += 1
                else: # It's a phrase
                    if item_lower in content:
                        count += 1
            
            results.append({
                "keyword": item,
                "count": count
            })
        
        # Sort by count desc
        results.sort(key=lambda x: x["count"], reverse=True)
        return results

    return {
        "words": count_matches(extracted["words"]),
        "phrases": count_matches(extracted["phrases"])
    }
