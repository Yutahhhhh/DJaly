from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session

from api.schemas.performance_metadata import PerformanceMetadataRead, PerformanceMetadataWrite
from app.services.performance_metadata_app_service import (
    PerformanceMetadataAppService,
    PerformanceMetadataConflictError,
    PerformanceMetadataNotFoundError,
    PerformanceMetadataValidationError,
)
from infra.database.connection import get_session


router = APIRouter()


def _raise_service_error(exc: Exception) -> None:
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
