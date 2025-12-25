from typing import Optional
from datetime import datetime
from sqlmodel import Field, SQLModel

class Setlist(SQLModel, table=True):
    __tablename__ = "setlists"
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    description: Optional[str] = None
    
    # --- Added Metadata ---
    display_order: int = Field(default=0)
    genre: Optional[str] = None
    target_duration: Optional[float] = None
    rating: Optional[int] = None
    
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)

class SetlistTrack(SQLModel, table=True):
    __tablename__ = "setlist_tracks"
    id: Optional[int] = Field(default=None, primary_key=True)
    setlist_id: int = Field(foreign_key="setlists.id")
    track_id: int = Field(foreign_key="tracks.id")
    position: int
    transition_note: Optional[str] = None
    wordplay_json: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.now)
