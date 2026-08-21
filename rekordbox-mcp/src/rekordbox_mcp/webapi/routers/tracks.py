"""Track metadata REST API (read-only)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from rekordbox_mcp.mcp.server import get_repository

router = APIRouter(prefix="/api/tracks", tags=["tracks"])


@router.get("")
async def list_tracks() -> dict[str, Any]:
    """List all tracks in the Rekordbox library."""
    repo = get_repository()
    tracks = repo.get_tracks()
    return {
        "success": True,
        "tracks": [track.model_dump(mode="json") for track in tracks],
    }


@router.get("/{track_id}")
async def get_track(track_id: int) -> dict[str, Any]:
    """Get a single track's full metadata, including cues, phrases, waveform,
    vocal track, and beat grid."""
    repo = get_repository()
    track = repo.get_track(track_id)
    if not track:
        raise HTTPException(status_code=404, detail=f"Track {track_id} not found")
    return {
        "success": True,
        "track": track.model_dump(mode="json"),
    }


@router.get("/{track_id}/analysis")
async def get_track_analysis(track_id: int) -> dict[str, Any]:
    """Get a track's raw ANLZ analysis data (phrases, beat grid, waveform,
    vocal track)."""
    repo = get_repository()
    track = repo.get_track(track_id)
    if not track:
        raise HTTPException(status_code=404, detail=f"Track {track_id} not found")

    anlz_data = repo.read_anlz_files(track)

    return {
        "success": True,
        "track_id": track_id,
        "phrases": [p.model_dump(mode="json") for p in anlz_data.get("phrases") or []],
        "beat_grid": anlz_data["beat_grid"].model_dump(mode="json") if anlz_data.get("beat_grid") else None,
        "waveform": [w.model_dump(mode="json") for w in anlz_data.get("waveform") or []],
        "vocal_track": anlz_data.get("vocal_track"),
    }
