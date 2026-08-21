"""Backup management tools for Rekordbox MCP."""

from __future__ import annotations

import asyncio
from typing import Any, Literal

from fastmcp import FastMCP

from rekordbox_mcp.domain.models import BackupType, OperationMode
from rekordbox_mcp.mcp.server import (
    get_backup_manager,
    get_mcp,
    get_settings_instance,
)

mcp: FastMCP = get_mcp()


def _check_write_mode() -> OperationMode:
    """Check if we're in a write mode and Rekordbox is not running."""
    settings = get_settings_instance()
    mode = settings.mode
    if mode == OperationMode.READONLY:
        raise RuntimeError("Write operations require masterdb or xml mode. Use set_mode to change mode.")
    if mode == OperationMode.MASTERDB:
        from rekordbox_mcp.mcp.server import get_connection

        conn = get_connection()
        if conn.is_rekordbox_running():
            raise RuntimeError("Rekordbox is running. Close Rekordbox before write operations.")
    return mode


@mcp.tool(
    name="backup_now",
    description="Create a backup (full or differential)",
    tags={"backup", "write"},
    annotations={"readOnlyHint": False, "destructiveHint": False},
)
async def backup_now(
    type: Literal["full", "differential"] = "full",
    description: str = "",
    name: str | None = None,
    entity_type: str | None = None,
    entity_ids: list[str | int] | None = None,
    changeset_id: str | None = None,
    force: bool = False,
) -> dict[str, Any]:
    """Create a backup (full or differential)."""
    _check_write_mode()

    manager = get_backup_manager()
    backup_type = BackupType(type)

    if backup_type == BackupType.FULL:
        backup = await asyncio.to_thread(
            manager.backup_full,
            name=name,
            description=description,
            force=force,
        )
    else:
        if not entity_type or not entity_ids:
            return {"success": False, "error": "entity_type and entity_ids required for differential backup"}
        backup = await asyncio.to_thread(
            manager.backup_differential,
            entity_type=entity_type,
            entity_ids=entity_ids,
            name=name,
            description=description,
            changeset_id=changeset_id,
        )

    if not backup:
        return {"success": False, "error": "Backup failed"}

    return {
        "success": True,
        "backup": backup.model_dump(mode="json"),
    }


@mcp.tool(
    name="list_backups",
    description="List all backups with optional type filter",
    tags={"backup", "read"},
    annotations={"readOnlyHint": True},
)
async def list_backups(
    type: Literal["full", "differential", "all"] = "all",
    include_protected: bool = True,
) -> dict[str, Any]:
    """List all backups with optional type filter."""
    manager = get_backup_manager()
    backup_type = BackupType(type) if type != "all" else None

    backups = await asyncio.to_thread(manager.list_backups, backup_type, include_protected)

    return {
        "success": True,
        "backups": [b.model_dump(mode="json") for b in backups],
        "count": len(backups),
    }


@mcp.tool(
    name="protect_backup",
    description="Protect or unprotect a backup from auto-cleanup",
    tags={"backup", "write"},
    annotations={"readOnlyHint": False, "destructiveHint": False},
)
async def protect_backup(backup_id: str, protect: bool = True) -> dict[str, Any]:
    """Protect or unprotect a backup from auto-cleanup."""
    _check_write_mode()

    manager = get_backup_manager()
    backup = await asyncio.to_thread(manager.protect_backup, backup_id, protect)

    if not backup:
        return {"success": False, "error": f"Backup {backup_id} not found"}

    return {
        "success": True,
        "backup": backup.model_dump(mode="json"),
    }


@mcp.tool(
    name="restore_backup",
    description="Restore a full backup to the database",
    tags={"backup", "write"},
    annotations={"readOnlyHint": False, "destructiveHint": True},
)
async def restore_backup(backup_id: str, target_path: str | None = None) -> dict[str, Any]:
    """Restore a full backup to the database."""
    if get_settings_instance().mode != OperationMode.MASTERDB:
        return {
            "success": False,
            "error": "restore_backup is only available in masterdb mode; it cannot restore a database in xml mode.",
        }
    _check_write_mode()

    manager = get_backup_manager()
    target = None
    if target_path:
        from pathlib import Path
        target = Path(target_path)

    try:
        success = await asyncio.to_thread(manager.restore_backup, backup_id, target)
        return {"success": success, "backup_id": backup_id}
    except Exception as e:
        return {"success": False, "error": str(e)}


@mcp.tool(
    name="restore_differential_backup",
    description="Restore a differential backup (returns records for manual application)",
    tags={"backup", "read"},
    annotations={"readOnlyHint": True},
)
async def restore_differential_backup(backup_id: str) -> dict[str, Any]:
    """Restore a differential backup (returns records for manual application)."""
    manager = get_backup_manager()

    try:
        data = await asyncio.to_thread(manager.restore_differential, backup_id)
        return {"success": True, "data": data}
    except Exception as e:
        return {"success": False, "error": str(e)}


@mcp.tool(
    name="cleanup_backups",
    description="Clean up old backups according to retention policy",
    tags={"backup", "write"},
    annotations={"readOnlyHint": False, "destructiveHint": True},
)
async def cleanup_backups() -> dict[str, Any]:
    """Clean up old backups according to retention policy."""
    _check_write_mode()

    manager = get_backup_manager()
    deleted = await asyncio.to_thread(manager.cleanup)

    return {
        "success": True,
        "deleted": deleted,
    }


@mcp.tool(
    name="get_backup_usage",
    description="Get backup storage usage statistics",
    tags={"backup", "read"},
    annotations={"readOnlyHint": True},
)
async def get_backup_usage() -> dict[str, Any]:
    """Get backup storage usage statistics."""
    manager = get_backup_manager()
    usage = await asyncio.to_thread(manager.get_usage)

    return {
        "success": True,
        "usage": usage.model_dump(mode="json"),
    }


@mcp.tool(
    name="get_backup",
    description="Get a specific backup by ID",
    tags={"backup", "read"},
    annotations={"readOnlyHint": True},
)
async def get_backup(backup_id: str) -> dict[str, Any]:
    """Get a specific backup by ID."""
    manager = get_backup_manager()
    backup = await asyncio.to_thread(manager.get_backup, backup_id)

    if not backup:
        return {"success": False, "error": f"Backup {backup_id} not found"}

    return {
        "success": True,
        "backup": backup.model_dump(mode="json"),
    }


@mcp.tool(
    name="ensure_initial_backup",
    description="Ensure an initial protected full backup exists (call before first write)",
    tags={"backup", "write"},
    annotations={"readOnlyHint": False, "destructiveHint": False},
)
async def ensure_initial_backup() -> dict[str, Any]:
    """Ensure an initial protected full backup exists."""
    _check_write_mode()

    manager = get_backup_manager()
    backup = await asyncio.to_thread(manager.ensure_initial_backup)

    if not backup:
        return {"success": False, "error": "Failed to create initial backup"}

    return {
        "success": True,
        "backup": backup.model_dump(mode="json"),
    }
