from typing import Optional
from datetime import datetime
from sqlmodel import SQLModel

class TrackRead(SQLModel):
    id: int
    filepath: str
    title: str
    artist: str
    album: str
    genre: str
    year: Optional[int] = None
    duration: float
    bpm: float
    
    key: str
    scale: str
    energy: float
    danceability: float
    loudness: float
    brightness: float
    noisiness: float
    contrast: float
    
    loudness_range: float
    spectral_flux: float
    spectral_rolloff: float
    
    is_genre_verified: bool = False
    
    created_at: datetime
