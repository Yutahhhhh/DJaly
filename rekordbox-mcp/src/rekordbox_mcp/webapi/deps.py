"""Shared dependencies for the Rekordbox Web API routers."""

from __future__ import annotations

from fastapi import HTTPException

from rekordbox_mcp.domain.models import OperationMode
from rekordbox_mcp.mcp.server import get_connection, get_settings_instance


def check_write_mode() -> OperationMode:
    """Ensure the server is in a write-capable mode and Rekordbox is not running.

    Raises HTTPException(403) if in readonly mode, or HTTPException(409) if
    Rekordbox is currently running in masterdb mode.
    """
    settings = get_settings_instance()
    mode = settings.mode
    if mode == OperationMode.READONLY:
        raise HTTPException(
            status_code=403,
            detail="Write operations require masterdb or xml mode. Use PUT /api/mode to change mode.",
        )
    if mode == OperationMode.MASTERDB:
        conn = get_connection()
        if conn.is_rekordbox_running():
            raise HTTPException(
                status_code=409,
                detail="Rekordbox is running. Close Rekordbox before write operations.",
            )
    return mode
