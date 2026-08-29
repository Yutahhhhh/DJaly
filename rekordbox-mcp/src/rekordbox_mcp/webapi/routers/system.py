"""System status and mode management REST API."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from rekordbox_mcp.domain.models import OperationMode, ServerStatus
from rekordbox_mcp.mcp.server import (
    cleanup_services,
    get_backup_manager,
    get_connection,
    get_repository,
    get_settings_instance,
    initialize_services,
)

router = APIRouter(prefix="/api", tags=["system"])


class SetModeRequest(BaseModel):
    mode: str


@router.get("/status")
async def get_status() -> dict[str, Any]:
    """Get comprehensive server status."""
    settings = get_settings_instance()
    mode = settings.mode

    db_connected = False
    db_path = None
    track_count = 0
    playlist_count = 0
    db_error = None

    try:
        conn = get_connection()
        db_connected = conn.is_connected
        db_path = str(conn.db_path) if conn.db_path else None

        if db_connected:
            repo = get_repository()
            tracks = repo.get_tracks()
            track_count = len(tracks)
            playlists = repo.get_playlists()
            playlist_count = len(playlists)
    except Exception as e:
        # Surface read failures instead of silently reporting 0 counts as if
        # the library were empty (see RekordboxConnection.recover_from_error).
        db_error = str(e)

    rekordbox_running = False
    try:
        conn = get_connection()
        rekordbox_running = conn.is_rekordbox_running()
    except Exception:
        pass

    backup_usage = None
    last_backup = None
    try:
        backup_manager = get_backup_manager()
        usage = backup_manager.get_usage()
        backup_usage = usage.model_dump(mode="json")

        backups = backup_manager.list_backups(None, True)
        if backups:
            last_backup = backups[0].created_at.isoformat()
    except Exception:
        pass

    status = ServerStatus(
        mode=mode,
        db_connected=db_connected,
        db_path=db_path,
        rekordbox_running=rekordbox_running,
        track_count=track_count,
        playlist_count=playlist_count,
        db_error=db_error,
        backup_usage=backup_usage,
        last_backup=last_backup,
    )

    return {
        "success": True,
        "status": status.model_dump(mode="json"),
    }


@router.get("/mode")
async def get_mode() -> dict[str, Any]:
    """Get the current operation mode."""
    settings = get_settings_instance()
    current_mode = OperationMode(settings.mode).value
    return {
        "success": True,
        "mode": current_mode,
        "description": {
            "readonly": "Read-only access to tracks, cues, playlists",
            "xml": "Export cues to Rekordbox collection XML (Automark-for-Rekordbox compatible)",
            "masterdb": "Direct database writes (requires Rekordbox to be closed)",
        }.get(current_mode, "Unknown mode"),
    }


@router.put("/mode")
async def set_mode(body: SetModeRequest) -> dict[str, Any]:
    """Set the operation mode."""
    try:
        new_mode = OperationMode(body.mode)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid mode: {body.mode}. Must be one of: readonly, xml, masterdb",
        )

    settings = get_settings_instance()
    old_mode = OperationMode(settings.mode)

    if new_mode == old_mode:
        return {
            "success": True,
            "mode": new_mode.value,
            "message": f"Already in {new_mode.value} mode",
        }

    settings.mode = new_mode

    try:
        cleanup_services()
        initialize_services(settings, new_mode)
    except Exception as e:
        settings.mode = old_mode
        cleanup_services()
        initialize_services(settings, old_mode)
        raise HTTPException(status_code=500, detail=f"Failed to switch mode: {e}")

    return {
        "success": True,
        "mode": new_mode.value,
        "previous_mode": old_mode.value,
        "message": f"Switched from {old_mode.value} to {new_mode.value} mode",
    }
