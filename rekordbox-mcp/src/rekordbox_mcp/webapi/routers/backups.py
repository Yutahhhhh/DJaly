"""Backup management REST API."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from rekordbox_mcp.domain.models import BackupType
from rekordbox_mcp.mcp.server import get_backup_manager
from rekordbox_mcp.webapi.deps import check_write_mode

router = APIRouter(prefix="/api/backups", tags=["backups"])


class BackupNowRequest(BaseModel):
    type: Literal["full", "differential"] = "full"
    description: str = ""
    name: str | None = None
    entity_type: str | None = None
    entity_ids: list[str | int] | None = None
    changeset_id: str | None = None
    force: bool = False


class ProtectBackupRequest(BaseModel):
    protect: bool = True


class RestoreBackupRequest(BaseModel):
    target_path: str | None = None


@router.post("")
async def backup_now(body: BackupNowRequest) -> dict[str, Any]:
    """Create a backup (full or differential)."""
    check_write_mode()

    manager = get_backup_manager()
    backup_type = BackupType(body.type)

    if backup_type == BackupType.FULL:
        backup = manager.backup_full(
            name=body.name,
            description=body.description,
            force=body.force,
        )
    else:
        if not body.entity_type or not body.entity_ids:
            raise HTTPException(
                status_code=400,
                detail="entity_type and entity_ids required for differential backup",
            )
        backup = manager.backup_differential(
            entity_type=body.entity_type,
            entity_ids=body.entity_ids,
            name=body.name,
            description=body.description,
            changeset_id=body.changeset_id,
        )

    if not backup:
        raise HTTPException(status_code=500, detail="Backup failed")

    return {
        "success": True,
        "backup": backup.model_dump(mode="json"),
    }


@router.get("")
async def list_backups(
    type: Literal["full", "differential", "all"] = "all",
    include_protected: bool = True,
) -> dict[str, Any]:
    """List all backups with optional type filter."""
    manager = get_backup_manager()
    backup_type = BackupType(type) if type != "all" else None

    backups = manager.list_backups(backup_type, include_protected)

    return {
        "success": True,
        "backups": [b.model_dump(mode="json") for b in backups],
        "count": len(backups),
    }


@router.get("/usage")
async def get_backup_usage() -> dict[str, Any]:
    """Get backup storage usage statistics."""
    manager = get_backup_manager()
    usage = manager.get_usage()

    return {
        "success": True,
        "usage": usage.model_dump(mode="json"),
    }


@router.get("/{backup_id}")
async def get_backup(backup_id: str) -> dict[str, Any]:
    """Get a specific backup by ID."""
    manager = get_backup_manager()
    backup = manager.get_backup(backup_id)

    if not backup:
        raise HTTPException(status_code=404, detail=f"Backup {backup_id} not found")

    return {
        "success": True,
        "backup": backup.model_dump(mode="json"),
    }


@router.post("/{backup_id}/protect")
async def protect_backup(backup_id: str, body: ProtectBackupRequest) -> dict[str, Any]:
    """Protect or unprotect a backup from auto-cleanup."""
    check_write_mode()

    manager = get_backup_manager()
    backup = manager.protect_backup(backup_id, body.protect)

    if not backup:
        raise HTTPException(status_code=404, detail=f"Backup {backup_id} not found")

    return {
        "success": True,
        "backup": backup.model_dump(mode="json"),
    }


@router.post("/{backup_id}/restore")
async def restore_backup(backup_id: str, body: RestoreBackupRequest) -> dict[str, Any]:
    """Restore a full backup to the database."""
    check_write_mode()

    manager = get_backup_manager()
    target = Path(body.target_path) if body.target_path else None

    try:
        success = manager.restore_backup(backup_id, target)
        return {"success": success, "backup_id": backup_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/cleanup")
async def cleanup_backups() -> dict[str, Any]:
    """Clean up old backups according to retention policy."""
    check_write_mode()

    manager = get_backup_manager()
    deleted = manager.cleanup()

    return {
        "success": True,
        "deleted": deleted,
    }
