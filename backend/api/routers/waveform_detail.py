from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session

from app.services.waveform_detail_service import WaveformDetailError, waveform_detail
from domain.models.track import Track
from infra.database.connection import get_session

router = APIRouter(prefix="/api/play", tags=["play"])


@router.get("/tracks/{track_id}/waveform-detail")
def get_waveform_detail(
    track_id: int,
    bins: int | None = Query(None, ge=16, le=20000, description="間引き後のビン数。一覧のプレビューのように小さく描く用途で使う。"),
    session: Session = Depends(get_session),
):
    track = session.get(Track, track_id)
    if track is None:
        raise HTTPException(404, "Track not found")
    try:
        return waveform_detail(track.filepath, bins)
    except WaveformDetailError as exc:
        raise HTTPException(exc.status_code, str(exc)) from exc
