from typing import Optional
from sqlmodel import Field, SQLModel
from datetime import datetime

class Lyrics(SQLModel, table=True):
    __tablename__ = "lyrics"
    
    track_id: int = Field(primary_key=True, foreign_key="tracks.id")
    content: str = Field(default="")
    source: str = Field(default="user") # user, ai, metadata
    language: Optional[str] = Field(default=None)
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
