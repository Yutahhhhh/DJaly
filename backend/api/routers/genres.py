from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session
from typing import List, Optional
from infra.database.connection import get_session
from models import Track
from api.schemas.genres import (
    GenreBatchUpdateRequest, 
    GroupedSuggestionSummary, 
    TrackSuggestion, 
    GenreCleanupGroup,
    GenreCleanupRequest,
    GenreApplyRequest,
    GenreAnalysisApplyRequest,
    GenreBatchUpdateResponse,
    AnalysisMode
)
from api.schemas.track import TrackRead
from app.services.recommendation_app_service import RecommendationAppService
from app.services.genre_app_service import GenreAppService

router = APIRouter()

@router.get("/api/genres/list", response_model=List[str])
def get_all_genres(session: Session = Depends(get_session)):
    """
    Get all unique genres.
    """
    service = GenreAppService(session)
    return service.get_all_genres()

@router.get("/api/genres/subgenres", response_model=List[str])
def get_all_subgenres(session: Session = Depends(get_session)):
    """
    Get all unique subgenres.
    """
    service = GenreAppService(session)
    return service.get_all_subgenres()

@router.get("/api/genres/unknown", response_model=List[TrackRead])
def get_unknown_tracks(
    offset: int = 0,
    limit: int = 50,
    mode: AnalysisMode = AnalysisMode.GENRE,
    session: Session = Depends(get_session)
):
    service = GenreAppService(session)
    return service.get_unknown_tracks(offset, limit, mode)

@router.get("/api/genres/unknown-ids", response_model=List[int])
def get_unknown_track_ids(
    mode: AnalysisMode = AnalysisMode.GENRE,
    session: Session = Depends(get_session)
):
    service = GenreAppService(session)
    return service.get_all_unknown_track_ids(mode)

@router.get("/api/genres/grouped-suggestions", response_model=List[GroupedSuggestionSummary])
def get_grouped_suggestions(
    offset: int = 0,
    limit: int = 10,
    threshold: float = 0.85,
    mode: AnalysisMode = AnalysisMode.GENRE,
    session: Session = Depends(get_session)
):
    service = RecommendationAppService(session)
    results = service.get_grouped_suggestions(
        limit=limit, 
        offset=offset, 
        threshold=threshold, 
        summary_only=True,
        mode=mode.value
    )
    return results

@router.get("/api/genres/grouped-suggestions/{track_id}", response_model=List[TrackSuggestion])
def get_suggestions_for_track(
    track_id: int,
    threshold: float = 0.85,
    session: Session = Depends(get_session)
):
    service = RecommendationAppService(session)
    results = service.get_suggestions_for_track(track_id=track_id, threshold=threshold)
    return results

@router.post("/api/genres/batch-update", response_model=GenreBatchUpdateResponse)
def batch_update_genres(
    request: GenreBatchUpdateRequest,
    session: Session = Depends(get_session)
):
    service = GenreAppService(session)
    try:
        return service.batch_update_genres(request)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/api/genres/apply-analyses")
def apply_genre_analyses(
    request: GenreAnalysisApplyRequest,
    session: Session = Depends(get_session)
):
    """
    外部モデル(例: Gemini Gem)が判定したジャンル/サブジャンル結果を一括適用する。
    各要素: track_id, genre, subgenre, confidence, reason。
    """
    service = GenreAppService(session)
    results = service.apply_genre_analyses(
        [item.model_dump() for item in request.analyses],
        request.mode,
        request.overwrite,
    )
    return {"results": [r.model_dump() for r in results]}

@router.get("/api/genres/cleanup-suggestions", response_model=List[GenreCleanupGroup])
def get_cleanup_suggestions(
    mode: AnalysisMode = AnalysisMode.GENRE,
    session: Session = Depends(get_session)
):
    """
    表記揺れのあるジャンルグループを取得する
    """
    service = GenreAppService(session)
    return service.get_cleanup_suggestions(mode)

@router.post("/api/genres/cleanup-execute")
def execute_cleanup(
    request: GenreCleanupRequest,
    session: Session = Depends(get_session)
):
    """
    指定したトラックのジャンルを一括更新する
    """
    service = GenreAppService(session)
    return service.execute_cleanup(request.target_genre, request.track_ids, request.mode)

@router.post("/api/genres/apply-to-files")
def apply_genres_to_files(
    request: GenreApplyRequest,
    session: Session = Depends(get_session)
):
    """
    Apply DB genres to actual file metadata for specified tracks.
    """
    service = GenreAppService(session)
    return service.apply_genres_to_files(request.track_ids)
