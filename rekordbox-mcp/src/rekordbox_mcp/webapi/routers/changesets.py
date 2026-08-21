"""ChangeSet management REST API."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from rekordbox_mcp.mcp.server import get_changeset_manager
from rekordbox_mcp.webapi.deps import check_write_mode

router = APIRouter(prefix="/api", tags=["changesets"])


class CreateChangesetRequest(BaseModel):
    name: str


class ApplyChangesetRequest(BaseModel):
    dry_run: bool = False


@router.post("/changesets")
async def create_changeset(body: CreateChangesetRequest) -> dict[str, Any]:
    """Create a new empty ChangeSet."""
    check_write_mode()

    manager = get_changeset_manager()
    changeset = manager.create_changeset(body.name)

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


@router.get("/changesets")
async def list_changesets() -> dict[str, Any]:
    """List all ChangeSets."""
    manager = get_changeset_manager()
    changesets = manager.list_changesets()

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


@router.get("/changesets/{changeset_id}/preview")
async def preview_changeset(changeset_id: str) -> dict[str, Any]:
    """Preview the changes in a ChangeSet."""
    manager = get_changeset_manager()
    preview = manager.preview(changeset_id)

    if not preview:
        raise HTTPException(status_code=404, detail=f"ChangeSet {changeset_id} not found")

    return {"success": True, "preview": preview}


@router.post("/changesets/{changeset_id}/apply")
async def apply_changeset(changeset_id: str, body: ApplyChangesetRequest) -> dict[str, Any]:
    """Apply a ChangeSet atomically."""
    check_write_mode()

    manager = get_changeset_manager()
    result = manager.apply(changeset_id, body.dry_run)

    return result


@router.post("/changesets/{changeset_id}/undo")
async def undo_changeset(changeset_id: str) -> dict[str, Any]:
    """Undo an applied ChangeSet."""
    check_write_mode()

    manager = get_changeset_manager()
    result = manager.undo(changeset_id)

    return result


@router.post("/changesets/{changeset_id}/rollback")
async def rollback_changeset(changeset_id: str) -> dict[str, Any]:
    """Rollback a ChangeSet (alias for undo)."""
    check_write_mode()

    manager = get_changeset_manager()
    result = manager.rollback(changeset_id)

    return result


@router.delete("/changesets/{changeset_id}")
async def delete_changeset(changeset_id: str) -> dict[str, Any]:
    """Delete a ChangeSet (only if not applied)."""
    check_write_mode()

    manager = get_changeset_manager()
    try:
        success = manager.delete_changeset(changeset_id)
        if not success:
            raise HTTPException(status_code=404, detail=f"ChangeSet {changeset_id} not found")
        return {"success": True, "changeset_id": changeset_id}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/audit-log")
async def get_audit_log(
    limit: int = 100,
    entity_type: str | None = None,
    changeset_id: str | None = None,
    entity_id: str | None = None,
    offset: int = 0,
) -> dict[str, Any]:
    """Get audit log entries with optional filters."""
    manager = get_changeset_manager()
    logs = manager.get_audit_log(
        changeset_id=changeset_id,
        entity_type=entity_type,
        entity_id=entity_id,
        limit=limit,
    )

    if offset > 0:
        logs = logs[offset:]

    return {
        "success": True,
        "logs": [log.model_dump(mode="json") for log in logs],
        "count": len(logs),
        "limit": limit,
        "offset": offset,
    }
