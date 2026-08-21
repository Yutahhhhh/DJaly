"""ChangeSet domain logic - atomic change management with preview, apply, undo, rollback."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Callable, Protocol
from uuid import uuid4

from rekordbox_mcp.domain.models import (
    AuditLogEntry,
    ChangeAction,
    ChangeSet,
    ChangeSetItem,
    OperationMode,
)


class ChangeExecutor(Protocol):
    """Protocol for executing changes."""

    def execute(self, item: ChangeSetItem) -> bool: ...
    def revert(self, item: ChangeSetItem) -> bool: ...


class AuditLoggerProtocol(Protocol):
    """Protocol for audit logging."""

    def log(
        self,
        operation: str,
        entity_type: str,
        entity_id: str | int,
        mode: OperationMode,
        changes: dict[str, Any],
        success: bool,
        error: str | None = None,
        changeset_id: str | None = None,
        backup_id: str | None = None,
    ) -> None: ...


class BackupManagerProtocol(Protocol):
    """Protocol for backup management."""

    def backup_differential(self, entity_type: str, entity_ids: list[str | int]) -> str | None: ...


class ChangeSetManager:
    """Manages ChangeSets for atomic operations with preview, apply, undo, rollback."""

    def __init__(
        self,
        executor: ChangeExecutor | None = None,
        audit_logger: AuditLoggerProtocol | None = None,
        backup_manager: BackupManagerProtocol | None = None,
        mode: OperationMode = OperationMode.READONLY,
    ):
        self._executor = executor
        self._audit_logger = audit_logger
        self._backup_manager = backup_manager
        self._mode = mode
        self._changesets: dict[str, ChangeSet] = {}
        self._applied_order: list[str] = []  # Track application order for undo

    # =========================================================================
    # ChangeSet Creation
    # =========================================================================

    def create_changeset(self, name: str) -> ChangeSet:
        """Create a new empty ChangeSet."""
        changeset = ChangeSet(name=name)
        self._changesets[changeset.id] = changeset
        return changeset

    def get_changeset(self, changeset_id: str) -> ChangeSet | None:
        """Get a ChangeSet by ID."""
        return self._changesets.get(changeset_id)

    def list_changesets(self) -> list[ChangeSet]:
        """List all ChangeSets."""
        return list(self._changesets.values())

    # =========================================================================
    # Adding Changes
    # =========================================================================

    def add_change(
        self,
        changeset_id: str,
        action: ChangeAction,
        entity_type: str,
        entity_id: str | int,
        old_data: dict[str, Any] | None = None,
        new_data: dict[str, Any] | None = None,
        **metadata,
    ) -> ChangeSetItem | None:
        """Add a change to a ChangeSet."""
        changeset = self._changesets.get(changeset_id)
        if not changeset:
            return None
        if changeset.is_applied:
            raise ValueError("Cannot modify an already applied ChangeSet")
        return changeset.add_change(action, entity_type, entity_id, old_data, new_data, **metadata)

    def add_create(
        self,
        changeset_id: str,
        entity_type: str,
        entity_id: str | int,
        new_data: dict[str, Any],
        **metadata,
    ) -> ChangeSetItem | None:
        """Add a CREATE change."""
        return self.add_change(
            changeset_id, ChangeAction.CREATE, entity_type, entity_id, None, new_data, **metadata
        )

    def add_update(
        self,
        changeset_id: str,
        entity_type: str,
        entity_id: str | int,
        old_data: dict[str, Any],
        new_data: dict[str, Any],
        **metadata,
    ) -> ChangeSetItem | None:
        """Add an UPDATE change."""
        return self.add_change(
            changeset_id, ChangeAction.UPDATE, entity_type, entity_id, old_data, new_data, **metadata
        )

    def add_delete(
        self,
        changeset_id: str,
        entity_type: str,
        entity_id: str | int,
        old_data: dict[str, Any],
        **metadata,
    ) -> ChangeSetItem | None:
        """Add a DELETE change."""
        return self.add_change(
            changeset_id, ChangeAction.DELETE, entity_type, entity_id, old_data, None, **metadata
        )

    def add_replace(
        self,
        changeset_id: str,
        entity_type: str,
        entity_id: str | int,
        old_data: dict[str, Any],
        new_data: dict[str, Any],
        **metadata,
    ) -> ChangeSetItem | None:
        """Add a REPLACE change."""
        return self.add_change(
            changeset_id, ChangeAction.REPLACE, entity_type, entity_id, old_data, new_data, **metadata
        )

    # =========================================================================
    # Preview
    # =========================================================================

    def preview(self, changeset_id: str) -> dict[str, Any] | None:
        """Generate a preview of changes in a ChangeSet."""
        changeset = self._changesets.get(changeset_id)
        if not changeset:
            return None

        preview_items = []
        for item in changeset.items:
            preview_items.append(
                {
                    "id": item.id,
                    "action": item.action.value,
                    "entity_type": item.entity_type,
                    "entity_id": item.entity_id,
                    "old_data": item.old_data,
                    "new_data": item.new_data,
                    "metadata": item.metadata,
                }
            )

        return {
            "changeset_id": changeset.id,
            "name": changeset.name,
            "item_count": len(changeset.items),
            "is_applied": changeset.is_applied,
            "is_rolled_back": changeset.is_rolled_back,
            "dry_run": changeset.dry_run,
            "changes": preview_items,
        }

    # =========================================================================
    # Apply
    # =========================================================================

    def apply(self, changeset_id: str, dry_run: bool = False) -> dict[str, Any]:
        """
        Apply a ChangeSet atomically.

        Args:
            changeset_id: ID of the ChangeSet to apply
            dry_run: If True, only simulate without executing

        Returns:
            Result dict with success status and details
        """
        changeset = self._changesets.get(changeset_id)
        if not changeset:
            return {"success": False, "error": "ChangeSet not found"}

        if changeset.is_applied:
            return {"success": False, "error": "ChangeSet already applied"}

        if changeset.is_rolled_back:
            return {"success": False, "error": "ChangeSet was rolled back"}

        if self._mode == OperationMode.READONLY and not dry_run:
            return {"success": False, "error": "Cannot apply in readonly mode"}

        changeset.dry_run = dry_run
        applied_items: list[ChangeSetItem] = []
        backup_id = None

        try:
            # Create differential backup before applying (if not dry run)
            if not dry_run and self._backup_manager:
                entity_ids = [item.entity_id for item in changeset.items]
                entity_types = list({item.entity_type for item in changeset.items})
                # Backup each entity type
                for etype in entity_types:
                    ids = [eid for item in changeset.items if item.entity_type == etype for eid in [item.entity_id]]
                    backup_id = self._backup_manager.backup_differential(etype, ids)
                    if backup_id:
                        break  # Use first backup ID

            # Execute each change
            for item in changeset.items:
                if dry_run:
                    # Just validate
                    if self._executor and not self._executor.execute(item):
                        raise RuntimeError(f"Dry run validation failed for {item.entity_type}:{item.entity_id}")
                else:
                    if self._executor and not self._executor.execute(item):
                        raise RuntimeError(f"Failed to execute change: {item.entity_type}:{item.entity_id}")

                applied_items.append(item)

                # Log success
                if self._audit_logger:
                    self._audit_logger.log(
                        operation=f"changeset_{item.action.value}",
                        entity_type=item.entity_type,
                        entity_id=item.entity_id,
                        mode=self._mode,
                        changes={"old": item.old_data, "new": item.new_data},
                        success=True,
                        changeset_id=changeset.id,
                        backup_id=backup_id,
                    )

            # Mark as applied
            changeset.is_applied = True
            changeset.applied_at = datetime.now()
            self._applied_order.append(changeset.id)

            return {
                "success": True,
                "changeset_id": changeset.id,
                "applied_count": len(applied_items),
                "dry_run": dry_run,
                "backup_id": backup_id,
            }

        except Exception as e:
            # Rollback on failure
            if not dry_run:
                self._rollback_applied(applied_items, changeset.id)

            # Log failure
            if self._audit_logger:
                for item in applied_items:
                    self._audit_logger.log(
                        operation=f"changeset_{item.action.value}",
                        entity_type=item.entity_type,
                        entity_id=item.entity_id,
                        mode=self._mode,
                        changes={"old": item.old_data, "new": item.new_data},
                        success=False,
                        error=str(e),
                        changeset_id=changeset.id,
                        backup_id=backup_id,
                    )

            return {"success": False, "error": str(e), "changeset_id": changeset.id}

    def _rollback_applied(self, applied_items: list[ChangeSetItem], changeset_id: str) -> None:
        """Rollback already applied items in reverse order."""
        for item in reversed(applied_items):
            if self._executor:
                try:
                    self._executor.revert(item)
                except Exception:
                    pass  # Best effort rollback

    # =========================================================================
    # Undo / Rollback
    # =========================================================================

    def undo(self, changeset_id: str) -> dict[str, Any]:
        """
        Undo an applied ChangeSet by reverting its changes.
        This creates a new inverse ChangeSet and applies it.
        """
        changeset = self._changesets.get(changeset_id)
        if not changeset:
            return {"success": False, "error": "ChangeSet not found"}

        if not changeset.is_applied:
            return {"success": False, "error": "ChangeSet not applied"}

        if changeset.is_rolled_back:
            return {"success": False, "error": "ChangeSet already rolled back"}

        if self._mode == OperationMode.READONLY:
            return {"success": False, "error": "Cannot undo in readonly mode"}

        # Create inverse changeset
        inverse = ChangeSet(name=f"Undo: {changeset.name}")
        for item in reversed(changeset.items):
            inverse_action = self._inverse_action(item.action)
            inverse.add_change(
                inverse_action,
                item.entity_type,
                item.entity_id,
                old_data=item.new_data,
                new_data=item.old_data,
                **item.metadata,
            )

        self._changesets[inverse.id] = inverse

        # Apply inverse
        result = self.apply(inverse.id, dry_run=False)
        if result["success"]:
            changeset.is_rolled_back = True
            changeset.rolled_back_at = datetime.now()
            if changeset.id in self._applied_order:
                self._applied_order.remove(changeset.id)

        return result

    def rollback(self, changeset_id: str) -> dict[str, Any]:
        """
        Rollback a ChangeSet (alias for undo).
        """
        return self.undo(changeset_id)

    def _inverse_action(self, action: ChangeAction) -> ChangeAction:
        """Get the inverse action."""
        inverse_map = {
            ChangeAction.CREATE: ChangeAction.DELETE,
            ChangeAction.DELETE: ChangeAction.CREATE,
            ChangeAction.UPDATE: ChangeAction.UPDATE,  # Swap old/new
            ChangeAction.REPLACE: ChangeAction.REPLACE,  # Swap old/new
            ChangeAction.MERGE: ChangeAction.MERGE,
        }
        return inverse_map.get(action, ChangeAction.UPDATE)

    # =========================================================================
    # Audit Log
    # =========================================================================

    def get_audit_log(
        self,
        changeset_id: str | None = None,
        entity_type: str | None = None,
        entity_id: str | int | None = None,
        limit: int = 100,
    ) -> list[AuditLogEntry]:
        """Get audit log entries (delegates to audit logger if available)."""
        if self._audit_logger and hasattr(self._audit_logger, "get_logs"):
            return self._audit_logger.get_logs(
                changeset_id=changeset_id,
                entity_type=entity_type,
                entity_id=entity_id,
                limit=limit,
            )
        return []

    # =========================================================================
    # Utility
    # =========================================================================

    def delete_changeset(self, changeset_id: str) -> bool:
        """Delete a ChangeSet (only if not applied)."""
        changeset = self._changesets.get(changeset_id)
        if not changeset:
            return False
        if changeset.is_applied:
            raise ValueError("Cannot delete applied ChangeSet")
        del self._changesets[changeset_id]
        return True

    def clear_history(self) -> None:
        """Clear all ChangeSets."""
        self._changesets.clear()
        self._applied_order.clear()

    def get_applied_changesets(self) -> list[ChangeSet]:
        """Get all applied ChangeSets in order."""
        return [self._changesets[cid] for cid in self._applied_order if cid in self._changesets]