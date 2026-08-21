"""Audit logging for tracking all operations with persistence."""

from __future__ import annotations

import json
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

from rekordbox_mcp.config import Settings, get_settings
from rekordbox_mcp.domain.models import AuditLogEntry, OperationMode


class AuditLogger:
    """Thread-safe audit logger with JSON file persistence."""

    def __init__(
        self,
        settings: Settings | None = None,
        audit_dir: Path | None = None,
    ):
        self._settings = settings or get_settings()
        self._lock = threading.RLock()

        # Determine audit directory
        if audit_dir is not None:
            self._audit_dir = audit_dir
        else:
            # Default to backup_dir/audit/ or ~/.rekordbox-mcp/audit/
            backup_dir = self._settings.backup_dir_path
            self._audit_dir = backup_dir / "audit"

        self._audit_dir.mkdir(parents=True, exist_ok=True)
        self._log_file = self._audit_dir / "audit.log.jsonl"
        self._index_file = self._audit_dir / "audit_index.json"

        # In-memory index for fast lookups
        self._index: dict[str, dict[str, Any]] = {}
        self._load_index()

    def _load_index(self) -> None:
        """Load audit index from disk."""
        if self._index_file.exists():
            try:
                with open(self._index_file, "r", encoding="utf-8") as f:
                    self._index = json.load(f)
            except Exception:
                self._index = {}

    def _save_index(self) -> None:
        """Save audit index to disk."""
        with open(self._index_file, "w", encoding="utf-8") as f:
            json.dump(self._index, f, indent=2, default=str)

    def _append_log(self, entry: AuditLogEntry) -> None:
        """Append a log entry to the JSONL file."""
        with open(self._log_file, "a", encoding="utf-8") as f:
            f.write(entry.model_dump_json() + "\n")

    def log(
        self,
        operation: str,
        entity_type: str,
        entity_id: str | int,
        mode: OperationMode | str,
        changes: dict[str, Any] | None = None,
        success: bool = True,
        error: str | None = None,
        changeset_id: str | None = None,
        backup_id: str | None = None,
        user: str = "mcp",
    ) -> AuditLogEntry:
        """
        Log an operation.

        Args:
            operation: Operation name (e.g., 'add_hot_cue', 'create_playlist')
            entity_type: Entity type (e.g., 'cue', 'playlist', 'track')
            entity_id: Entity identifier
            mode: Operation mode (readonly, xml, masterdb)
            changes: Change details dictionary
            success: Whether operation succeeded
            error: Error message if failed
            changeset_id: Associated ChangeSet ID
            backup_id: Associated Backup ID
            user: User/agent identifier

        Returns:
            The created AuditLogEntry
        """
        if isinstance(mode, str):
            mode = OperationMode(mode)

        entry = AuditLogEntry(
            operation=operation,
            entity_type=entity_type,
            entity_id=entity_id,
            user=user,
            mode=mode,
            changes=changes or {},
            success=success,
            error=error,
            changeset_id=changeset_id,
            backup_id=backup_id,
        )

        with self._lock:
            self._append_log(entry)
            # Update index
            self._index[entry.id] = {
                "id": entry.id,
                "timestamp": entry.timestamp.isoformat(),
                "operation": entry.operation,
                "entity_type": entry.entity_type,
                "entity_id": str(entry.entity_id),
                "mode": entry.mode.value,
                "success": entry.success,
                "changeset_id": entry.changeset_id,
                "backup_id": entry.backup_id,
            }
            self._save_index()

        return entry

    def get_logs(
        self,
        changeset_id: str | None = None,
        entity_type: str | None = None,
        entity_id: str | int | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[AuditLogEntry]:
        """
        Get audit logs with optional filters.

        Args:
            changeset_id: Filter by changeset ID
            entity_type: Filter by entity type
            entity_id: Filter by entity ID
            limit: Maximum number of entries to return
            offset: Number of entries to skip

        Returns:
            List of AuditLogEntry objects (newest first)
        """
        with self._lock:
            # Filter index entries
            filtered = []
            for idx_entry in self._index.values():
                if changeset_id and idx_entry.get("changeset_id") != changeset_id:
                    continue
                if entity_type and idx_entry.get("entity_type") != entity_type:
                    continue
                if entity_id is not None and str(idx_entry.get("entity_id")) != str(entity_id):
                    continue
                filtered.append(idx_entry)

            # Sort by timestamp descending (newest first)
            filtered.sort(key=lambda x: x["timestamp"], reverse=True)

            # Apply pagination
            paginated = filtered[offset : offset + limit]

            # Load full entries from JSONL
            entries = []
            if not paginated:
                return entries

            # Build a set of IDs to load
            ids_to_load = {e["id"] for e in paginated}

            # Read JSONL file and collect matching entries
            if self._log_file.exists():
                with open(self._log_file, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            entry_data = json.loads(line)
                            if entry_data.get("id") in ids_to_load:
                                entries.append(AuditLogEntry(**entry_data))
                        except Exception:
                            continue

            # Sort entries to match index order
            id_to_entry = {e.id: e for e in entries}
            result = [id_to_entry[e["id"]] for e in paginated if e["id"] in id_to_entry]

            return result

    def get_log_count(
        self,
        changeset_id: str | None = None,
        entity_type: str | None = None,
        entity_id: str | int | None = None,
    ) -> int:
        """Get total count of logs matching filters."""
        with self._lock:
            count = 0
            for idx_entry in self._index.values():
                if changeset_id and idx_entry.get("changeset_id") != changeset_id:
                    continue
                if entity_type and idx_entry.get("entity_type") != entity_type:
                    continue
                if entity_id is not None and str(idx_entry.get("entity_id")) != str(entity_id):
                    continue
                count += 1
            return count

    def clear_logs(self, before: datetime | None = None) -> int:
        """
        Clear audit logs (with optional date filter).

        Args:
            before: Clear logs before this timestamp (keeps newer logs)

        Returns:
            Number of entries cleared
        """
        with self._lock:
            if before is None:
                # Clear all
                self._log_file.unlink(missing_ok=True)
                self._index.clear()
                self._save_index()
                return 0  # We don't track total count easily

            # Filter index
            to_remove = []
            for entry_id, idx_entry in self._index.items():
                entry_time = datetime.fromisoformat(idx_entry["timestamp"])
                if entry_time < before:
                    to_remove.append(entry_id)

            for entry_id in to_remove:
                del self._index[entry_id]

            self._save_index()

            # Rebuild JSONL file (filter out old entries)
            if self._log_file.exists():
                temp_file = self._log_file.with_suffix(".tmp")
                kept = 0
                with open(self._log_file, "r", encoding="utf-8") as f_in:
                    with open(temp_file, "w", encoding="utf-8") as f_out:
                        for line in f_in:
                            line = line.strip()
                            if not line:
                                continue
                            try:
                                entry_data = json.loads(line)
                                entry_time = datetime.fromisoformat(entry_data["timestamp"])
                                if entry_time >= before:
                                    f_out.write(line + "\n")
                                    kept += 1
                            except Exception:
                                continue

                temp_file.replace(self._log_file)

            return len(to_remove)

    @property
    def audit_dir(self) -> Path:
        """Get the audit log directory."""
        return self._audit_dir

    @property
    def log_file(self) -> Path:
        """Get the audit log file path."""
        return self._log_file