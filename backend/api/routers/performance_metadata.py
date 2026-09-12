from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session

from api.schemas.performance_metadata import BeatGrid, CueSlotsRequest, GridAnalysisRequest, PerformanceMetadataRead, PerformanceMetadataWrite, RekordboxCueBulkImportRead, RekordboxCueBulkImportRequest, RekordboxCueImportRequest
from app.services.grid_candidate_service import GridCandidateService
from domain.services.analysis.rhythm_grid import GridAnalysisError
from infra.rekordbox_grid import RekordboxGridError
from infra.rekordbox_cues import RekordboxCueError, RekordboxCueTrackNotFoundError
from app.services.performance_metadata_app_service import (
    PerformanceMetadataAppService,
    PerformanceMetadataConflictError,
    PerformanceMetadataNotFoundError,
    PerformanceMetadataValidationError,
)
from infra.database.connection import get_session
from api.schemas.performance_metadata import GridBatchRequest
from app.services.analysis_job_service import analysis_job_service


router = APIRouter()


@router.post("/api/grid-jobs/plan")
def plan_grid_job(request: GridBatchRequest):
    return analysis_job_service.plan(track_ids=request.track_ids, features=["rhythm"], only_outdated=request.only_outdated)


@router.post("/api/grid-jobs")
def start_grid_job(request: GridBatchRequest):
    try:
        return analysis_job_service.start(track_ids=request.track_ids, features=["rhythm"], only_outdated=request.only_outdated, workers=1)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/api/grid-jobs")
def grid_job_status():
    # Same durable queue as selective reanalysis. Never start a second worker.
    return analysis_job_service.status()


@router.post("/api/grid-jobs/{job_id}/{action}")
def control_grid_job(job_id: str, action: str):
    try:
        job = analysis_job_service.status(job_id)
        if job["config"]["features"] != ["rhythm"]:
            raise ValueError("この画面ではグリッドの再解析だけを操作できます")
        if action == "pause":
            return analysis_job_service.pause(job_id)
        if action in {"resume", "retry"}:
            return analysis_job_service.resume(job_id, workers=1, retry_failed=action == "retry")
        raise ValueError("Unknown grid job action")
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


def _raise_service_error(exc: Exception) -> None:
    if isinstance(exc, GridAnalysisError):
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    if isinstance(exc, RekordboxGridError):
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if isinstance(exc, RekordboxCueTrackNotFoundError):
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if isinstance(exc, RekordboxCueError):
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if isinstance(exc, PerformanceMetadataNotFoundError):
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if isinstance(exc, PerformanceMetadataConflictError):
        raise HTTPException(
            status_code=409,
            detail={"message": str(exc), "current_revision": exc.current_revision},
        ) from exc
    if isinstance(exc, PerformanceMetadataValidationError):
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    raise exc


@router.post("/api/tracks/performance-metadata/cue-points")
def get_cue_points(
    request: CueSlotsRequest,
    session: Session = Depends(get_session),
) -> dict[str, list[float | None]]:
    """Hot cue positions for a page of tracks, so a list can draw them on its
    preview waveforms without fetching (and grid-analysing) each track."""
    summary = PerformanceMetadataAppService(session).cue_points_summary(request.track_ids)
    return {str(track_id): positions for track_id, positions in summary.items()}


@router.post(
    "/api/tracks/cues-rekordbox/import",
    response_model=RekordboxCueBulkImportRead,
)
def import_all_rekordbox_cues(
    request: RekordboxCueBulkImportRequest,
    session: Session = Depends(get_session),
) -> RekordboxCueBulkImportRead:
    try:
        return PerformanceMetadataAppService(session).import_all_rekordbox_cues(request)
    except Exception as exc:
        _raise_service_error(exc)


@router.get(
    "/api/tracks/{track_id}/performance-metadata",
    response_model=PerformanceMetadataRead,
)
def get_performance_metadata(
    track_id: int,
    session: Session = Depends(get_session),
) -> PerformanceMetadataRead:
    try:
        return PerformanceMetadataAppService(session).get(track_id)
    except Exception as exc:
        _raise_service_error(exc)


@router.post("/api/tracks/{track_id}/grid-analysis", response_model=BeatGrid)
def analyze_beat_grid(track_id: int, request: GridAnalysisRequest,
                      session: Session = Depends(get_session)) -> BeatGrid:
    # Synchronous routes run in FastAPI's threadpool; expensive DSP is additionally
    # isolated in one timeout-bounded subprocess, keeping transport/UI responsive.
    try:
        track = PerformanceMetadataAppService(session)._track(track_id)
        return GridCandidateService(session).analysis(track, force=request.force)
    except Exception as exc:
        _raise_service_error(exc)


@router.post("/api/tracks/{track_id}/grid-rekordbox", response_model=BeatGrid)
def restore_rekordbox_grid(track_id: int,
                           session: Session = Depends(get_session)) -> BeatGrid:
    try:
        track = PerformanceMetadataAppService(session)._track(track_id)
        grid = GridCandidateService(session).rekordbox(track, refresh=True)
        if grid is None:
            raise GridAnalysisError("No rekordbox PQTZ grid is available for this audio file", 404)
        return grid
    except OSError as exc:
        raise HTTPException(status_code=503, detail="The rekordbox analysis file is unavailable") from exc
    except Exception as exc:
        _raise_service_error(exc)


@router.post(
    "/api/tracks/{track_id}/cues-rekordbox",
    response_model=PerformanceMetadataRead,
)
def import_rekordbox_cues(
    track_id: int,
    request: RekordboxCueImportRequest,
    session: Session = Depends(get_session),
) -> PerformanceMetadataRead:
    try:
        return PerformanceMetadataAppService(session).import_rekordbox_cues(track_id, request)
    except Exception as exc:
        _raise_service_error(exc)


@router.put(
    "/api/tracks/{track_id}/performance-metadata",
    response_model=PerformanceMetadataRead,
)
def replace_performance_metadata(
    track_id: int,
    request: PerformanceMetadataWrite,
    session: Session = Depends(get_session),
) -> PerformanceMetadataRead:
    try:
        return PerformanceMetadataAppService(session).replace(track_id, request)
    except Exception as exc:
        _raise_service_error(exc)
