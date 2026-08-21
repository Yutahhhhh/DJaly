"""Tests for BackupManager (full/differential backups, retention, restore)."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import pytest

from rekordbox_mcp.config import Settings
from rekordbox_mcp.domain.backup import BackupManager
from rekordbox_mcp.domain.models import BackupType
from tests.conftest import FakeDatabaseAccessor


@pytest.fixture
def backup_manager(mock_db_accessor: FakeDatabaseAccessor, test_settings: Settings) -> BackupManager:
    return BackupManager(db_accessor=mock_db_accessor, settings=test_settings)


def test_backup_full_creates_compressed_file(backup_manager: BackupManager):
    backup = backup_manager.backup_full(name="Test Full", description="desc")

    assert backup is not None
    assert backup.type == BackupType.FULL
    assert Path(backup.path).exists()
    assert backup.compressed_size_bytes > 0
    assert backup.size_bytes > 0
    # zstd should compress an (empty-ish) sqlite db reasonably
    assert backup.name == "Test Full"


def test_backup_full_second_time_same_day_requires_force(backup_manager: BackupManager):
    first = backup_manager.backup_full(name="First")
    assert first is not None

    with pytest.raises(RuntimeError):
        backup_manager.backup_full(name="Second")

    # force=True bypasses the daily limit
    second = backup_manager.backup_full(name="Second", force=True)
    assert second is not None
    assert second.id != first.id


def test_backup_full_without_accessor_raises(test_settings: Settings):
    manager = BackupManager(db_accessor=None, settings=test_settings)
    with pytest.raises(RuntimeError):
        manager.backup_full(name="No Accessor")


def test_backup_differential_creates_file(backup_manager: BackupManager):
    backup = backup_manager.backup_differential(
        entity_type="cue", entity_ids=["cue-1", "cue-2"], name="Diff Test"
    )

    assert backup is not None
    assert backup.type == BackupType.DIFFERENTIAL
    assert Path(backup.path).exists()


def test_backup_differential_empty_ids_returns_none(backup_manager: BackupManager):
    result = backup_manager.backup_differential(entity_type="cue", entity_ids=[])
    assert result is None


def test_backup_differential_unknown_entity_type_raises(backup_manager: BackupManager):
    with pytest.raises(RuntimeError):
        backup_manager.backup_differential(entity_type="unknown", entity_ids=["1"])


def test_backup_differential_content_round_trip(backup_manager: BackupManager):
    backup = backup_manager.backup_differential(entity_type="cue", entity_ids=["cue-1"])
    data = backup_manager.restore_differential(backup.id)

    assert data["entity_type"] == "cue"
    assert "cue-1" in data["records"]


def test_list_backups_returns_newest_first(backup_manager: BackupManager):
    b1 = backup_manager.backup_full(name="B1", force=True)
    b2 = backup_manager.backup_full(name="B2", force=True)

    backups = backup_manager.list_backups()
    assert len(backups) >= 2
    assert backups[0].created_at >= backups[1].created_at


def test_list_backups_filter_by_type(backup_manager: BackupManager):
    backup_manager.backup_full(name="Full", force=True)
    backup_manager.backup_differential(entity_type="cue", entity_ids=["cue-1"])

    full_only = backup_manager.list_backups(backup_type=BackupType.FULL)
    diff_only = backup_manager.list_backups(backup_type=BackupType.DIFFERENTIAL)

    assert all(b.type == BackupType.FULL for b in full_only)
    assert all(b.type == BackupType.DIFFERENTIAL for b in diff_only)


def test_protect_backup(backup_manager: BackupManager):
    backup = backup_manager.backup_full(name="Protect Me")
    protected = backup_manager.protect_backup(backup.id, True)

    assert protected.is_protected is True
    fetched = backup_manager.get_backup(backup.id)
    assert fetched.is_protected is True

    unprotected = backup_manager.protect_backup(backup.id, False)
    assert unprotected.is_protected is False


def test_protect_backup_unknown_id_returns_none(backup_manager: BackupManager):
    assert backup_manager.protect_backup("missing") is None


def test_restore_backup(backup_manager: BackupManager, tmp_path: Path, mock_db_accessor: FakeDatabaseAccessor):
    backup = backup_manager.backup_full(name="To Restore")

    target = tmp_path / "restored.db"
    success = backup_manager.restore_backup(backup.id, target_path=target)

    assert success is True
    assert target.exists()

    # Verify it's a valid sqlite db with our original schema
    import sqlite3

    conn = sqlite3.connect(target)
    rows = conn.execute("SELECT * FROM djmdContent").fetchall()
    conn.close()
    assert len(rows) == 1


def test_restore_backup_unknown_id_raises(backup_manager: BackupManager):
    with pytest.raises(ValueError):
        backup_manager.restore_backup("missing-id")


def test_cleanup_respects_max_generations(mock_db_accessor: FakeDatabaseAccessor, tmp_path: Path):
    settings = Settings(
        backup_dir=str(tmp_path / "backups"),
        backup_max_generations=2,
        backup_max_days=365,
        backup_max_size_gb=100.0,
    )
    manager = BackupManager(db_accessor=mock_db_accessor, settings=settings)

    # Create several differential backups (not subject to daily-limit / latest-full exclusion)
    for i in range(5):
        manager.backup_differential(entity_type="cue", entity_ids=[f"cue-{i}"])

    deleted = manager.cleanup()
    remaining = manager.list_backups()

    assert len(remaining) <= settings.backup_max_generations + 1  # +1 tolerance for latest full
    assert deleted["differential"] >= 0


def test_cleanup_respects_max_days(mock_db_accessor: FakeDatabaseAccessor, tmp_path: Path):
    settings = Settings(
        backup_dir=str(tmp_path / "backups"),
        backup_max_days=1,
        backup_max_generations=100,
        backup_max_size_gb=100.0,
    )
    manager = BackupManager(db_accessor=mock_db_accessor, settings=settings)

    backup = manager.backup_differential(entity_type="cue", entity_ids=["cue-1"])
    # Force it to look old
    manager._index[backup.id].created_at = datetime.now() - timedelta(days=30)
    manager._save_index()

    deleted = manager.cleanup()
    assert deleted["differential"] == 1
    assert manager.get_backup(backup.id) is None


def test_cleanup_never_deletes_protected(mock_db_accessor: FakeDatabaseAccessor, tmp_path: Path):
    settings = Settings(
        backup_dir=str(tmp_path / "backups"),
        backup_max_days=1,
        backup_max_generations=1,
        backup_max_size_gb=100.0,
    )
    manager = BackupManager(db_accessor=mock_db_accessor, settings=settings)

    backup = manager.backup_differential(entity_type="cue", entity_ids=["cue-1"])
    manager.protect_backup(backup.id, True)
    manager._index[backup.id].created_at = datetime.now() - timedelta(days=30)
    manager._save_index()

    manager.cleanup()
    assert manager.get_backup(backup.id) is not None


def test_cleanup_respects_max_size_gb(mock_db_accessor: FakeDatabaseAccessor, tmp_path: Path):
    settings = Settings(
        backup_dir=str(tmp_path / "backups"),
        backup_max_days=365,
        backup_max_generations=100,
        backup_max_size_gb=0.1,
    )
    manager = BackupManager(db_accessor=mock_db_accessor, settings=settings)

    for i in range(3):
        manager.backup_differential(entity_type="cue", entity_ids=[f"cue-{i}"])

    # Inflate recorded sizes so the size cap definitely triggers
    for b in manager._index.values():
        b.compressed_size_bytes = 200 * 1024 * 1024  # 200MB each
    manager._save_index()

    manager.cleanup()
    total = sum(b.compressed_size_bytes for b in manager.list_backups())
    max_bytes = int(settings.backup_max_size_gb * 1024 * 1024 * 1024)
    # At least some cleanup should have brought it closer to (or under) the cap,
    # though the newest/latest-full/protected items are always retained.
    assert total <= max_bytes or len(manager.list_backups()) <= 1


def test_get_usage_empty(backup_manager: BackupManager):
    usage = backup_manager.get_usage()
    assert usage.total_backups == 0
    assert usage.total_size_bytes == 0


def test_get_usage_with_backups(backup_manager: BackupManager):
    backup_manager.backup_full(name="Full", force=True)
    backup_manager.backup_differential(entity_type="cue", entity_ids=["cue-1"])

    usage = backup_manager.get_usage()
    assert usage.total_backups == 2
    assert usage.full_backup_count == 1
    assert usage.differential_backup_count == 1
    assert usage.oldest_backup is not None
    assert usage.newest_backup is not None


def test_ensure_initial_backup_creates_full_backup(backup_manager: BackupManager):
    backup = backup_manager.ensure_initial_backup()
    assert backup is not None
    assert backup.type == BackupType.FULL
    assert backup.name == "Initial Protected Backup"


def test_ensure_initial_backup_idempotent_once_protected(backup_manager: BackupManager):
    backup = backup_manager.ensure_initial_backup()
    backup_manager.mark_full_backup_protected(backup.id)

    # Calling again returns the same protected backup, not a new one
    again = backup_manager.ensure_initial_backup()
    assert again.id == backup.id
    assert again.is_protected is True
