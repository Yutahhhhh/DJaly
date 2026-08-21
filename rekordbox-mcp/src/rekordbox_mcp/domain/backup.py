"""Backup domain logic - full/differential backups with zstd compression and retention policies."""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import tempfile
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Protocol
from uuid import uuid4

import zstandard as zstd

from rekordbox_mcp.config import Settings, get_settings
from rekordbox_mcp.domain.models import BackupInfo, BackupType, BackupUsage


class DatabaseAccessor(Protocol):
    """Protocol for database access."""

    def get_connection(self) -> sqlite3.Connection: ...
    def get_db_path(self) -> Path: ...
    def get_db_version(self) -> str: ...


class BackupManager:
    """Manages backups with compression, retention, and protection policies."""

    def __init__(
        self,
        db_accessor: DatabaseAccessor | None = None,
        settings: Settings | None = None,
    ):
        self._db_accessor = db_accessor
        self._settings = settings or get_settings()
        self._backup_dir = self._settings.backup_dir_path
        self._backup_dir.mkdir(parents=True, exist_ok=True)
        self._index_path = self._backup_dir / "backup_index.json"
        self._compressor = zstd.ZstdCompressor(level=self._settings.backup_compression_level)
        self._decompressor = zstd.ZstdDecompressor()
        self._index: dict[str, BackupInfo] = {}
        self._load_index()

    # =========================================================================
    # Index Management
    # =========================================================================

    def _load_index(self) -> None:
        """Load backup index from disk."""
        if self._index_path.exists():
            try:
                with open(self._index_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self._index = {k: BackupInfo(**v) for k, v in data.items()}
            except Exception:
                self._index = {}

    def _save_index(self) -> None:
        """Save backup index to disk."""
        data = {k: v.model_dump(mode="json") for k, v in self._index.items()}
        with open(self._index_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, default=str)

    def _get_backup_path(self, backup_id: str, backup_type: BackupType) -> Path:
        """Get the file path for a backup."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        suffix = ".db.zst" if backup_type == BackupType.FULL else ".diff.zst"
        return self._backup_dir / f"{backup_type.value}_{timestamp}_{backup_id[:8]}{suffix}"

    # =========================================================================
    # Full Backup
    # =========================================================================

    def backup_full(
        self,
        name: str | None = None,
        description: str = "",
        force: bool = False,
    ) -> BackupInfo | None:
        """
        Create a full database backup.

        Args:
            name: Backup name (auto-generated if not provided)
            description: Backup description
            force: Force backup even if one exists today

        Returns:
            BackupInfo if successful, None otherwise
        """
        if not self._db_accessor:
            raise RuntimeError("Database accessor not configured")

        # Check daily limit (1 full backup per day)
        today = datetime.now().date()
        if not force:
            for backup in self._index.values():
                if backup.type == BackupType.FULL and backup.created_at.date() == today:
                    if not backup.is_protected:
                        raise RuntimeError(
                            "Full backup already exists for today. Use force=True to override."
                        )

        # Create backup
        backup_id = str(uuid4())
        backup_path = self._get_backup_path(backup_id, BackupType.FULL)

        try:
            # Copy database to temp file
            db_path = self._db_accessor.get_db_path()
            with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
                tmp_path = Path(tmp.name)

            shutil.copy2(db_path, tmp_path)

            # Compress
            original_size = tmp_path.stat().st_size
            with open(tmp_path, "rb") as f_in:
                with open(backup_path, "wb") as f_out:
                    with self._compressor.stream_writer(f_out) as compressor:
                        shutil.copyfileobj(f_in, compressor)

            compressed_size = backup_path.stat().st_size

            # Cleanup temp
            tmp_path.unlink(missing_ok=True)

            # Create backup info
            backup_info = BackupInfo(
                id=backup_id,
                name=name or f"Full Backup {datetime.now().strftime('%Y-%m-%d %H:%M')}",
                type=BackupType.FULL,
                path=str(backup_path),
                size_bytes=original_size,
                compressed_size_bytes=compressed_size,
                db_version=self._db_accessor.get_db_version(),
                description=description,
            )

            self._index[backup_id] = backup_info
            self._save_index()

            # Run cleanup after backup
            self.cleanup()

            return backup_info

        except Exception as e:
            backup_path.unlink(missing_ok=True)
            tmp_path.unlink(missing_ok=True)
            raise RuntimeError(f"Full backup failed: {e}") from e

    # =========================================================================
    # Differential Backup
    # =========================================================================

    def backup_differential(
        self,
        entity_type: str,
        entity_ids: list[str | int],
        name: str | None = None,
        description: str = "",
        changeset_id: str | None = None,
    ) -> BackupInfo | None:
        """
        Create a differential backup for specific entities.

        Args:
            entity_type: Type of entity (e.g., 'cue', 'playlist', 'track')
            entity_ids: List of entity IDs to backup
            name: Backup name
            description: Backup description
            changeset_id: Associated ChangeSet ID

        Returns:
            BackupInfo if successful, None otherwise
        """
        if not self._db_accessor:
            raise RuntimeError("Database accessor not configured")

        if not entity_ids:
            return None

        backup_id = str(uuid4())
        backup_path = self._get_backup_path(backup_id, BackupType.DIFFERENTIAL)

        try:
            conn = self._db_accessor.get_connection()
            cursor = conn.cursor()

            # Build differential data
            diff_data = {
                "entity_type": entity_type,
                "entity_ids": [str(eid) for eid in entity_ids],
                "timestamp": datetime.now().isoformat(),
                "db_version": self._db_accessor.get_db_version(),
                "records": {},
            }

            # Fetch records based on entity type
            table_map = {
                "cue": "djmdCue",
                "playlist": "djmdPlaylist",
                "track": "djmdContent",
                "content": "djmdContent",
            }

            table = table_map.get(entity_type.lower())
            if not table:
                raise ValueError(f"Unknown entity type: {entity_type}")

            placeholders = ",".join("?" * len(entity_ids))
            query = f"SELECT * FROM {table} WHERE ID IN ({placeholders})"
            cursor.execute(query, [str(eid) for eid in entity_ids])
            columns = [desc[0] for desc in cursor.description]

            for row in cursor.fetchall():
                record = dict(zip(columns, row))
                diff_data["records"][str(record["ID"])] = record

            # Write to temp file and compress
            with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as tmp:
                json.dump(diff_data, tmp, default=str)
                tmp_path = Path(tmp.name)

            original_size = tmp_path.stat().st_size
            with open(tmp_path, "rb") as f_in:
                with open(backup_path, "wb") as f_out:
                    with self._compressor.stream_writer(f_out) as compressor:
                        shutil.copyfileobj(f_in, compressor)

            compressed_size = backup_path.stat().st_size
            tmp_path.unlink(missing_ok=True)

            # Create backup info
            backup_info = BackupInfo(
                id=backup_id,
                name=name or f"Differential: {entity_type} ({len(entity_ids)} records)",
                type=BackupType.DIFFERENTIAL,
                path=str(backup_path),
                size_bytes=original_size,
                compressed_size_bytes=compressed_size,
                db_version=self._db_accessor.get_db_version(),
                description=description,
                changeset_id=changeset_id,
            )

            self._index[backup_id] = backup_info
            self._save_index()

            # Run cleanup after backup
            self.cleanup()

            return backup_info

        except Exception as e:
            backup_path.unlink(missing_ok=True)
            raise RuntimeError(f"Differential backup failed: {e}") from e

    # =========================================================================
    # Backup Listing
    # =========================================================================

    def list_backups(
        self,
        backup_type: BackupType | None = None,
        include_protected: bool = True,
    ) -> list[BackupInfo]:
        """List all backups, optionally filtered by type."""
        backups = list(self._index.values())

        if backup_type:
            backups = [b for b in backups if b.type == backup_type]

        if not include_protected:
            backups = [b for b in backups if not b.is_protected]

        # Sort by creation time, newest first
        backups.sort(key=lambda b: b.created_at, reverse=True)
        return backups

    def get_backup(self, backup_id: str) -> BackupInfo | None:
        """Get a specific backup by ID."""
        return self._index.get(backup_id)

    # =========================================================================
    # Protection
    # =========================================================================

    def protect_backup(self, backup_id: str, protect: bool = True) -> BackupInfo | None:
        """Protect or unprotect a backup from auto-cleanup."""
        backup = self._index.get(backup_id)
        if not backup:
            return None
        backup.is_protected = protect
        self._save_index()
        return backup

    # =========================================================================
    # Restore
    # =========================================================================

    def restore_backup(self, backup_id: str, target_path: Path | None = None) -> bool:
        """
        Restore a backup.

        Args:
            backup_id: ID of backup to restore
            target_path: Target path (defaults to original DB path)

        Returns:
            True if successful
        """
        backup = self._index.get(backup_id)
        if not backup:
            raise ValueError(f"Backup not found: {backup_id}")

        if not backup.path or not Path(backup.path).exists():
            raise FileNotFoundError(f"Backup file not found: {backup.path}")

        if not self._db_accessor:
            raise RuntimeError("Database accessor not configured")

        target = target_path or self._db_accessor.get_db_path()

        try:
            # Decompress
            with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
                tmp_path = Path(tmp.name)

            with open(backup.path, "rb") as f_in:
                with open(tmp_path, "wb") as f_out:
                    with self._decompressor.stream_reader(f_in) as reader:
                        shutil.copyfileobj(reader, f_out)

            # Verify it's a valid SQLite database
            test_conn = sqlite3.connect(tmp_path)
            test_conn.execute("SELECT 1")
            test_conn.close()

            # Replace target
            if target.exists():
                target.unlink()
            shutil.move(tmp_path, target)

            return True

        except Exception as e:
            tmp_path.unlink(missing_ok=True)
            raise RuntimeError(f"Restore failed: {e}") from e

    def restore_differential(self, backup_id: str) -> dict[str, Any]:
        """
        Restore a differential backup (returns records for manual application).

        Returns:
            Dict with entity_type, entity_ids, and records
        """
        backup = self._index.get(backup_id)
        if not backup:
            raise ValueError(f"Backup not found: {backup_id}")

        if backup.type != BackupType.DIFFERENTIAL:
            raise ValueError("Not a differential backup")

        if not backup.path or not Path(backup.path).exists():
            raise FileNotFoundError(f"Backup file not found: {backup.path}")

        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tmp:
            tmp_path = Path(tmp.name)

        try:
            with open(backup.path, "rb") as f_in:
                with open(tmp_path, "wb") as f_out:
                    with self._decompressor.stream_reader(f_in) as reader:
                        shutil.copyfileobj(reader, f_out)

            with open(tmp_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            tmp_path.unlink(missing_ok=True)
            return data

        except Exception as e:
            tmp_path.unlink(missing_ok=True)
            raise RuntimeError(f"Differential restore failed: {e}") from e

    # =========================================================================
    # Cleanup
    # =========================================================================

    def cleanup(self) -> dict[str, int]:
        """
        Clean up old backups according to retention policy.

        Policy:
        - Keep protected backups
        - Keep latest successful full backup
        - Keep up to max_generations backups
        - Keep backups within max_days
        - Keep total size under max_size_gb
        - Delete oldest first

        Returns:
            Dict with counts of deleted backups by type
        """
        deleted = {"full": 0, "differential": 0, "protected": 0}

        # Get all backups sorted by age (oldest first)
        all_backups = sorted(self._index.values(), key=lambda b: b.created_at)

        # Identify protected backups
        protected = [b for b in all_backups if b.is_protected]

        # Identify latest full backup
        full_backups = [b for b in all_backups if b.type == BackupType.FULL]
        latest_full = full_backups[-1] if full_backups else None

        # Determine which to delete
        to_delete: list[BackupInfo] = []

        for backup in all_backups:
            if backup.is_protected:
                continue
            if backup == latest_full:
                continue

            # Check age
            age_days = (datetime.now() - backup.created_at).days
            if age_days > self._settings.backup_max_days:
                to_delete.append(backup)
                continue

        # Check generation limit
        non_protected = [b for b in all_backups if not b.is_protected and b != latest_full]
        if len(non_protected) > self._settings.backup_max_generations:
            excess = len(non_protected) - self._settings.backup_max_generations
            to_delete.extend(non_protected[:excess])

        # Check size limit
        total_size = sum(b.compressed_size_bytes for b in self._index.values())
        max_size = int(self._settings.backup_max_size_gb * 1024 * 1024 * 1024)

        if total_size > max_size:
            # Sort by age, delete oldest non-protected, non-latest-full
            candidates = [b for b in all_backups if not b.is_protected and b != latest_full]
            candidates.sort(key=lambda b: b.created_at)
            for backup in candidates:
                if total_size <= max_size:
                    break
                if backup not in to_delete:
                    to_delete.append(backup)
                    total_size -= backup.compressed_size_bytes

        # Execute deletions
        for backup in to_delete:
            try:
                Path(backup.path).unlink(missing_ok=True)
                del self._index[backup.id]
                if backup.type == BackupType.FULL:
                    deleted["full"] += 1
                else:
                    deleted["differential"] += 1
            except Exception:
                pass  # Best effort

        self._save_index()
        return deleted

    # =========================================================================
    # Usage Statistics
    # =========================================================================

    def get_usage(self) -> BackupUsage:
        """Get backup storage usage statistics."""
        backups = list(self._index.values())

        if not backups:
            return BackupUsage()

        total_size = sum(b.size_bytes for b in backups)
        total_compressed = sum(b.compressed_size_bytes for b in backups)
        protected = [b for b in backups if b.is_protected]
        full = [b for b in backups if b.type == BackupType.FULL]
        diff = [b for b in backups if b.type == BackupType.DIFFERENTIAL]

        return BackupUsage(
            total_backups=len(backups),
            total_size_bytes=total_size,
            total_compressed_bytes=total_compressed,
            oldest_backup=min(b.created_at for b in backups),
            newest_backup=max(b.created_at for b in backups),
            protected_count=len(protected),
            full_backup_count=len(full),
            differential_backup_count=len(diff),
        )

    # =========================================================================
    # First Write Protection
    # =========================================================================

    def ensure_initial_backup(self) -> BackupInfo | None:
        """
        Ensure an initial protected full backup exists.
        Call before first write operation.
        """
        # Check if protected full backup exists
        for backup in self._index.values():
            if backup.type == BackupType.FULL and backup.is_protected:
                return backup

        # Create initial protected backup
        backup = self.backup_full(
            name="Initial Protected Backup",
            description="Automatic backup before first write operation",
            # A non-protected full backup may already exist today.  The first
            # write must still get its own protected snapshot.
            force=True,
        )
        if backup:
            return self.protect_backup(backup.id, True)
        return backup

    def mark_full_backup_protected(self, backup_id: str) -> BackupInfo | None:
        """Mark a full backup as protected (manual protection)."""
        return self.protect_backup(backup_id, True)
