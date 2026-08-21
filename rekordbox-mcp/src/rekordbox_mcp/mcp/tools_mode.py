"""Mode management tools for Rekordbox MCP."""

from __future__ import annotations

import asyncio
from typing import Any

from fastmcp import FastMCP

from rekordbox_mcp.domain.models import OperationMode, ServerStatus
from rekordbox_mcp.mcp.server import (
    get_backup_manager,
    get_connection,
    get_mcp,
    get_repository,
    get_settings_instance,
)

mcp: FastMCP = get_mcp()


@mcp.tool(
    name="set_mode",
    description="Set operation mode (readonly, xml, masterdb). Write operations require masterdb or xml mode.",
    tags={"mode", "write"},
    annotations={"readOnlyHint": False, "destructiveHint": False},
)
async def set_mode(mode: str) -> dict[str, Any]:
    """Set the operation mode."""
    try:
        new_mode = OperationMode(mode)
    except ValueError:
        return {
            "success": False,
            "error": f"Invalid mode: {mode}. Must be one of: readonly, xml, masterdb",
        }

    settings = get_settings_instance()
    old_mode = settings.mode

    if new_mode == old_mode:
        return {
            "success": True,
            "mode": new_mode.value,
            "message": f"Already in {new_mode.value} mode",
        }

    # Update settings
    settings.mode = new_mode

    # Reinitialize services with new mode
    from rekordbox_mcp.mcp.server import initialize_services, cleanup_services

    try:
        cleanup_services()
        initialize_services(settings, new_mode)
    except Exception as e:
        # Rollback on failure
        settings.mode = old_mode
        cleanup_services()
        initialize_services(settings, old_mode)
        return {"success": False, "error": f"Failed to switch mode: {e}"}

    return {
        "success": True,
        "mode": new_mode.value,
        "previous_mode": old_mode.value,
        "message": f"Switched from {old_mode.value} to {new_mode.value} mode",
    }


@mcp.tool(
    name="get_mode",
    description="Get the current operation mode",
    tags={"mode", "read"},
    annotations={"readOnlyHint": True},
)
async def get_mode() -> dict[str, Any]:
    """Get the current operation mode."""
    settings = get_settings_instance()
    return {
        "success": True,
        "mode": settings.mode.value,
        "description": {
            "readonly": "Read-only access to tracks, cues, playlists",
            "xml": "Export cues to Rekordbox collection XML (Automark-for-Rekordbox compatible)",
            "masterdb": "Direct database writes (requires Rekordbox to be closed)",
        }.get(settings.mode.value, "Unknown mode"),
    }


@mcp.tool(
    name="get_status",
    description="Get server status including DB connection, Rekordbox running state, track/playlist counts, backup usage, and current mode",
    tags={"mode", "status", "read"},
    annotations={"readOnlyHint": True},
)
async def get_status() -> dict[str, Any]:
    """Get comprehensive server status."""
    settings = get_settings_instance()
    mode = settings.mode

    # Check DB connection
    db_connected = False
    db_path = None
    track_count = 0
    playlist_count = 0

    try:
        conn = get_connection()
        db_connected = conn.is_connected
        db_path = str(conn.db_path) if conn.db_path else None

        if db_connected:
            repo = get_repository()
            tracks = await asyncio.to_thread(repo.get_tracks)
            track_count = len(tracks)
            playlists = await asyncio.to_thread(repo.get_playlists)
            playlist_count = len(playlists)
    except Exception:
        pass

    # Check if Rekordbox is running
    rekordbox_running = False
    try:
        conn = get_connection()
        rekordbox_running = conn.is_rekordbox_running()
    except Exception:
        pass

    # Get backup usage
    backup_usage = None
    last_backup = None
    try:
        backup_manager = get_backup_manager()
        usage = await asyncio.to_thread(backup_manager.get_usage)
        backup_usage = usage.model_dump(mode="json")

        backups = await asyncio.to_thread(backup_manager.list_backups, None, True)
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
        backup_usage=backup_usage,
        last_backup=last_backup,
    )

    return {
        "success": True,
        "status": status.model_dump(mode="json"),
    }