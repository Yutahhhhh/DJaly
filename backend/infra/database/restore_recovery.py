"""Crash recovery for the two-file library/analysis-queue restore unit."""
import json
import os
import shutil
from pathlib import Path


def _sync(path: Path) -> None:
    # Windows FlushFileBuffers (used by os.fsync) requires a writable handle.
    with path.open("r+b") as file:
        os.fsync(file.fileno())


def marker_path(db_path: Path) -> Path:
    return db_path.with_name(db_path.name + ".restore-state.json")


def begin_restore(db_path: Path, rollback: Path, queue_existed: bool) -> None:
    _sync(rollback)
    if queue_existed:
        _sync(Path(str(rollback) + ".analysis-jobs.sqlite3"))
    marker = marker_path(db_path)
    temp = marker.with_suffix(".partial")
    temp.write_text(json.dumps({"rollback": rollback.name, "queue_existed": queue_existed}), encoding="utf-8")
    _sync(temp)
    if os.name == "nt":
        # Windows cannot fsync a directory through a POSIX descriptor. Request
        # write-through for the atomic marker rename through the native API.
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        move = kernel.MoveFileExW
        move.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD]
        move.restype = wintypes.BOOL
        if not move(str(temp), str(marker), 0x1 | 0x8):
            raise ctypes.WinError(ctypes.get_last_error())
    else:
        os.replace(temp, marker)
        descriptor = os.open(marker.parent, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


def sync_restored_files(db_path: Path) -> None:
    """Persist the replacement pair before DuckDB reopens its exclusive handle."""
    _sync(db_path)
    queue = Path(str(db_path) + ".analysis-jobs.sqlite3")
    if queue.exists():
        _sync(queue)


def finish_restore(db_path: Path) -> None:
    """Clear recovery only after the persisted pair was successfully reopened."""
    marker_path(db_path).unlink(missing_ok=True)


def recover_pending_restore(db_path: Path) -> bool:
    marker = marker_path(db_path)
    if not marker.exists():
        return False
    state = json.loads(marker.read_text(encoding="utf-8"))
    name = state.get("rollback")
    if not isinstance(name, str) or Path(name).name != name or not name.startswith(db_path.name + ".pre-restore-"):
        raise ValueError("復元の回復記録が不正です")
    rollback = db_path.parent / name
    queue_rollback = Path(str(rollback) + ".analysis-jobs.sqlite3")
    if not rollback.is_file() or (state["queue_existed"] and not queue_rollback.is_file()):
        raise ValueError("復元前の退避データが見つかりません")
    shutil.copy2(rollback, db_path)
    Path(str(db_path) + ".wal").unlink(missing_ok=True)
    queue = Path(str(db_path) + ".analysis-jobs.sqlite3")
    for suffix in ("", "-wal", "-shm"):
        Path(str(queue) + suffix).unlink(missing_ok=True)
    if state["queue_existed"]:
        shutil.copy2(queue_rollback, queue)
    sync_restored_files(db_path)
    finish_restore(db_path)
    return True
