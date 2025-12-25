from pydantic import BaseModel
from typing import Optional
from datetime import datetime

class LyricsBase(BaseModel):
    content: str
    source: Optional[str] = "user"
    language: Optional[str] = None

class LyricsCreate(LyricsBase):
    track_id: int

class LyricsRead(LyricsBase):
    track_id: int
    created_at: datetime
    updated_at: datetime

class LyricsUpdate(BaseModel):
    content: Optional[str] = None
    source: Optional[str] = None
    language: Optional[str] = None
