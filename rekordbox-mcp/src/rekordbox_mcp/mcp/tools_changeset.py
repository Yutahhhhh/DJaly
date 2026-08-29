"""ChangeSet management tools for Rekordbox MCP."""

from __future__ import annotations

import asyncio
from typing import Any, Literal

from fastmcp import FastMCP

from rekordbox_mcp.domain.models import ChangeAction, OperationMode
from rekordbox_mcp.mcp.server import (
    get_changeset_manager,
    get_mcp,
    get_repository,
    get_settings_instance,
    ensure_initial_backup_if_needed,
    require_db,
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
    ensure_initial_backup_if_needed()
    return mode


@mcp.tool(
    name="create_changeset",
    description="Create a new empty ChangeSet for atomic operations",
    tags={"changeset", "write"},
    annotations={"readOnlyHint": False, "destructiveHint": False},
)
@require_db
async def create_changeset(name: str) -> dict[str, Any]:
    """Create a new empty ChangeSet."""
    _check_write_mode()

    manager = get_changeset_manager()
    changeset = await asyncio.to_thread(manager.create_changeset, name)

    return {
        "success": True,
        "changeset": {
            "id": changeset.id,
            "name": changeset.name,
            "created_at": changeset.created_at.isoformat(),
            "item_count": len(changeset.items),
            "is_applied": changeset.is_applied,
            "is_rolled_back": changeset.is_rolled_back,
        },
    }


@mcp.tool(
    name="preview_changeset",
    description="Preview the changes in a ChangeSet without applying",
    tags={"changeset", "read"},
    annotations={"readOnlyHint": True},
)
async def preview_changeset(changeset_id: str) -> dict[str, Any]:
    """Preview the changes in a ChangeSet."""
    manager = get_changeset_manager()
    preview = await asyncio.to_thread(manager.preview, changeset_id)

    if not preview:
        return {"success": False, "error": f"ChangeSet {changeset_id} not found"}

    return {"success": True, "preview": preview}


@mcp.tool(
    name="apply_changeset",
    description="Apply a ChangeSet atomically (with optional dry-run)",
    tags={"changeset", "write"},
    annotations={"readOnlyHint": False, "destructiveHint": False},
)
@require_db
async def apply_changeset(changeset_id: str, dry_run: bool = False) -> dict[str, Any]:
    """Apply a ChangeSet atomically."""
    _check_write_mode()

    manager = get_changeset_manager()
    result = await asyncio.to_thread(manager.apply, changeset_id, dry_run)

    return result


@mcp.tool(
    name="undo_changeset",
    description="Undo an applied ChangeSet by reverting its changes",
    tags={"changeset", "write"},
    annotations={"readOnlyHint": False, "destructiveHint": True},
)
@require_db
async def undo_changeset(changeset_id: str) -> dict[str, Any]:
    """Undo an applied ChangeSet."""
    _check_write_mode()

    manager = get_changeset_manager()
    result = await asyncio.to_thread(manager.undo, changeset_id)

    return result


@mcp.tool(
    name="rollback_changeset",
    description="Rollback a ChangeSet (alias for undo)",
    tags={"changeset", "write"},
    annotations={"readOnlyHint": False, "destructiveHint": True},
)
@require_db
async def rollback_changeset(changeset_id: str) -> dict[str, Any]:
    """Rollback a ChangeSet (alias for undo)."""
    _check_write_mode()

    manager = get_changeset_manager()
    result = await asyncio.to_thread(manager.rollback, changeset_id)

    return result


@mcp.tool(
    name="get_audit_log",
    description="Get audit log entries with optional filters",
    tags={"changeset", "audit", "read"},
    annotations={"readOnlyHint": True},
)
async def get_audit_log(
    limit: int = 100,
    entity_type: str | None = None,
    changeset_id: str | None = None,
    entity_id: str | int | None = None,
    offset: int = 0,
) -> dict[str, Any]:
    """Get audit log entries with optional filters."""
    manager = get_changeset_manager()
    logs = await asyncio.to_thread(
        manager.get_audit_log,
        changeset_id=changeset_id,
        entity_type=entity_type,
        entity_id=entity_id,
        limit=limit,
    )

    # Apply offset manually since the manager doesn't support it directly
    if offset > 0:
        logs = logs[offset:]

    return {
        "success": True,
        "logs": [log.model_dump(mode="json") for log in logs],
        "count": len(logs),
        "limit": limit,
        "offset": offset,
    }


@mcp.tool(
    name="list_changesets",
    description="List all ChangeSets",
    tags={"changeset", "read"},
    annotations={"readOnlyHint": True},
)
async def list_changesets() -> dict[str, Any]:
    """List all ChangeSets."""
    manager = get_changeset_manager()
    changesets = await asyncio.to_thread(manager.list_changesets)

    return {
        "success": True,
        "changesets": [
            {
                "id": cs.id,
                "name": cs.name,
                "created_at": cs.created_at.isoformat(),
                "item_count": len(cs.items),
                "is_applied": cs.is_applied,
                "is_rolled_back": cs.is_rolled_back,
                "applied_at": cs.applied_at.isoformat() if cs.applied_at else None,
                "rolled_back_at": cs.rolled_back_at.isoformat() if cs.rolled_back_at else None,
            }
            for cs in changesets
        ],
        "count": len(changesets),
    }


@mcp.tool(
    name="add_change_to_changeset",
    description="Add a change to an existing ChangeSet",
    tags={"changeset", "write"},
    annotations={"readOnlyHint": False, "destructiveHint": False},
)
@require_db
async def add_change_to_changeset(
    changeset_id: str,
    action: Literal["create", "update", "delete", "replace", "merge"],
    entity_type: str,
    entity_id: str | int,
    old_data: dict[str, Any] | None = None,
    new_data: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Add a change to an existing ChangeSet."""
    _check_write_mode()

    manager = get_changeset_manager()
    action_enum = ChangeAction(action)

    item = await asyncio.to_thread(
        manager.add_change,
        changeset_id,
        action_enum,
        entity_type,
        entity_id,
        old_data,
        new_data,
        **(metadata or {}),
    )

    if not item:
        return {"success": False, "error": f"ChangeSet {changeset_id} not found or already applied"}

    return {
        "success": True,
        "change": {
            "id": item.id,
            "action": item.action.value,
            "entity_type": item.entity_type,
            "entity_id": item.entity_id,
            "old_data": item.old_data,
            "new_data": item.new_data,
            "metadata": item.metadata,
        },
    }


@mcp.tool(
    name="delete_changeset",
    description="Delete a ChangeSet (only if not applied)",
    tags={"changeset", "write"},
    annotations={"readOnlyHint": False, "destructiveHint": True},
)
@require_db
async def delete_changeset(changeset_id: str) -> dict[str, Any]:
    """Delete a ChangeSet (only if not applied)."""
    _check_write_mode()

    manager = get_changeset_manager()
    try:
        success = await asyncio.to_thread(manager.delete_changeset, changeset_id)
        if not success:
            return {"success": False, "error": f"ChangeSet {changeset_id} not found"}
        return {"success": True, "changeset_id": changeset_id}
    except ValueError as e:
        return {"success": False, "error": str(e)}
