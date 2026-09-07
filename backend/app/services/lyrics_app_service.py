"""Validated, database-only lyrics registration shared by MCP tools."""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, field_validator
from sqlmodel import Session

from domain.models.lyrics import Lyrics
from domain.models.track import Track


class LyricsRegistration(BaseModel):
    track_id: int = Field(gt=0)
    content: str = Field(min_length=1, max_length=200_000)
    source: str = Field(default="user", min_length=1, max_length=2048)
    language: Optional[str] = Field(default=None, max_length=64)

    @field_validator("content", "source")
    @classmethod
    def nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return value


def register_lyrics(session: Session, items: list[LyricsRegistration], overwrite: bool = False) -> dict:
    if not 1 <= len(items) <= 100:
        raise ValueError("Provide between 1 and 100 lyrics registrations")
    ids = [item.track_id for item in items]
    if len(set(ids)) != len(ids):
        raise ValueError("Duplicate track IDs are not allowed")
    # Validate the entire batch before any writes; missing IDs cannot partially apply it.
    for track_id in ids:
        if session.get(Track, track_id) is None:
            raise ValueError(f"Track {track_id} not found")
    results = []
    for item in items:
        lyrics = session.get(Lyrics, item.track_id)
        if lyrics and lyrics.content.strip() and not overwrite:
            status = "skipped_existing"
        elif lyrics and (lyrics.content, lyrics.source, lyrics.language) == (item.content, item.source, item.language):
            status = "unchanged"
        else:
            status = "updated" if lyrics else "created"
            if lyrics is None:
                lyrics = Lyrics(track_id=item.track_id)
            lyrics.content = item.content
            lyrics.source = item.source
            lyrics.language = item.language
            lyrics.keywords_json = None
            lyrics.keywords_content_hash = None
            lyrics.updated_at = datetime.now()
            session.add(lyrics)
        results.append({"track_id": item.track_id, "status": status})
    session.commit()
    return {"count": len(results), "results": results}
