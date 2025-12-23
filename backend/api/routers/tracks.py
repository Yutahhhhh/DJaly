from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session
from typing import Optional, List
from infra.database.connection import get_session
from models import Track
from api.schemas.track import TrackRead
from app.services.track_app_service import TrackAppService
from app.services.recommendation_app_service import RecommendationAppService
from pydantic import BaseModel

router = APIRouter()

class GenreUpdate(BaseModel):
    genre: str

@router.patch("/api/tracks/{track_id}/genre")
def update_track_genre(
    track_id: int,
    update: GenreUpdate,
    session: Session = Depends(get_session)
):
    app_service = TrackAppService(session)
    track = app_service.update_genre(track_id, update.genre)
    if not track:
        raise HTTPException(status_code=404, detail="Track not found")
    return track

@router.get("/api/tracks/{track_id}/suggest-genre")
def suggest_track_genre(
    track_id: int,
    session: Session = Depends(get_session)
):
    service = RecommendationAppService(session)
    result = service.suggest_genre(track_id)
    return result

@router.get("/api/tracks/{track_id}/similar", response_model=List[TrackRead])
def get_similar_tracks(
    track_id: int,
    limit: int = 20,
    session: Session = Depends(get_session)
):
    """
    Vector Search: Find tracks similar to the given track_id using embeddings.
    """
    try:
        app_service = TrackAppService(session)
        return app_service.get_similar_tracks(track_id, limit)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Vector search failed: {str(e)}")

@router.get("/api/tracks", response_model=List[TrackRead])
def get_tracks(
    status: str = "all",
    title: Optional[str] = None,
    artist: Optional[str] = None,
    album: Optional[str] = None,
    genres: Optional[List[str]] = Query(None),
    key: Optional[str] = None, # "C Major", "Major", "Minor" etc.
    bpm: Optional[float] = None,
    bpm_range: float = 5.0,
    min_duration: Optional[float] = None,
    max_duration: Optional[float] = None,
    # New Feature Filters (0.0 - 1.0)
    min_energy: Optional[float] = None,
    max_energy: Optional[float] = None,
    min_danceability: Optional[float] = None,
    max_danceability: Optional[float] = None,
    min_brightness: Optional[float] = None,
    max_brightness: Optional[float] = None,
    min_year: Optional[int] = None,
    max_year: Optional[int] = None,
    # Vibe Search
    vibe_prompt: Optional[str] = None,
    limit: int = 100, 
    offset: int = 0, 
    session: Session = Depends(get_session)
):
    app_service = TrackAppService(session)
    return app_service.get_tracks(
        status=status,
        title=title,
        artist=artist,
        album=album,
        genres=genres,
        key=key,
        bpm=bpm,
        bpm_range=bpm_range,
        min_duration=min_duration,
        max_duration=max_duration,
        min_energy=min_energy,
        max_energy=max_energy,
        min_danceability=min_danceability,
        max_danceability=max_danceability,
        min_brightness=min_brightness,
        max_brightness=max_brightness,
        min_year=min_year,
        max_year=max_year,
        vibe_prompt=vibe_prompt,
        limit=limit,
        offset=offset
    )
