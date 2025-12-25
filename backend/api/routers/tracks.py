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

class TrackInfoUpdate(BaseModel):
    title: Optional[str] = None
    artist: Optional[str] = None
    album: Optional[str] = None
    year: Optional[int] = None

@router.patch("/api/tracks/{track_id}/info")
def update_track_info(
    track_id: int,
    update: TrackInfoUpdate,
    session: Session = Depends(get_session)
):
    track = session.get(Track, track_id)
    if not track:
        raise HTTPException(status_code=404, detail="Track not found")
    
    if update.title is not None: track.title = update.title
    if update.artist is not None: track.artist = update.artist
    if update.album is not None: track.album = update.album
    if update.year is not None: track.year = update.year
    
    session.add(track)
    session.commit()
    session.refresh(track)
    return track

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
    subgenres: Optional[List[str]] = Query(None),
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
    year_status: str = "all",
    lyrics_status: str = "all",
    lyrics: Optional[str] = None,
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
        subgenres=subgenres,
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
        year_status=year_status,
        lyrics_status=lyrics_status,
        lyrics=lyrics,
        vibe_prompt=vibe_prompt,
        limit=limit,
        offset=offset
    )

@router.get("/api/tracks/ids", response_model=List[int])
def get_track_ids(
    status: str = "all",
    title: Optional[str] = None,
    artist: Optional[str] = None,
    album: Optional[str] = None,
    genres: Optional[List[str]] = Query(None),
    subgenres: Optional[List[str]] = Query(None),
    key: Optional[str] = None,
    bpm: Optional[float] = None,
    bpm_range: float = 5.0,
    min_duration: Optional[float] = None,
    max_duration: Optional[float] = None,
    min_energy: Optional[float] = None,
    max_energy: Optional[float] = None,
    min_danceability: Optional[float] = None,
    max_danceability: Optional[float] = None,
    min_brightness: Optional[float] = None,
    max_brightness: Optional[float] = None,
    min_year: Optional[int] = None,
    max_year: Optional[int] = None,
    year_status: str = "all",
    lyrics_status: str = "all",
    lyrics: Optional[str] = None,
    vibe_prompt: Optional[str] = None,
    session: Session = Depends(get_session)
):
    app_service = TrackAppService(session)
    return app_service.get_track_ids(
        status=status,
        title=title,
        artist=artist,
        album=album,
        genres=genres,
        subgenres=subgenres,
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
        year_status=year_status,
        lyrics_status=lyrics_status,
        lyrics=lyrics,
        vibe_prompt=vibe_prompt
    )
