"""Rekordbox database connection management with pyrekordbox integration."""

from __future__ import annotations

import hashlib
import os
import platform
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from rekordbox_mcp.config import Settings, get_settings
from rekordbox_mcp.domain.models import OperationMode

# Try to import pyrekordbox.  MasterDatabase was removed from pyrekordbox in
# 0.4.x; Rekordbox6Database is the replacement for both read and write access.
try:
    import pyrekordbox
    from pyrekordbox import Rekordbox6Database
    from pyrekordbox.db6 import tables as db6_tables
    from pyrekordbox.utils import get_rekordbox_pid

    PYREKORDBOX_AVAILABLE = True
except ImportError:
    pyrekordbox = None
    Rekordbox6Database = None
    db6_tables = None
    get_rekordbox_pid = None


def is_rekordbox_database(path: Path | None) -> bool:
    """Return whether *path* has the Rekordbox master database schema.

    pyrekordbox can be installed in environments that only use the project's
    in-memory test backend.  An empty SQLite file (the usual test fixture) is
    not a Rekordbox database and must not be passed to pyrekordbox or subject
    to the running-Rekordbox write guard.
    """
    if path is None or not path.exists():
        return False
    try:
        with sqlite3.connect(str(path)) as conn:
            row = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='djmdContent'"
            ).fetchone()
        return row is not None
    except sqlite3.Error:
        # Current Rekordbox master.db files are SQLCipher databases and cannot
        # be inspected by the stdlib sqlite driver.  A non-empty unreadable
        # database is therefore still a candidate for pyrekordbox; empty test
        # fixtures remain mock databases.
        return path.stat().st_size > 0


class _Db6Table:
    """Small compatibility layer for pyrekordbox <=0.3 table API.

    The project historically consumed dictionaries from ``get_all`` and
    ``get_by_id``.  pyrekordbox 0.4 exposes SQLAlchemy models instead.
    Keeping the conversion here avoids spreading version-specific code over
    the repository.
    """

    def __init__(self, database: Any, model: Any):
        self.database = database
        self.model = model

    @staticmethod
    def _dict(row: Any) -> dict[str, Any]:
        data = row.to_dict() if hasattr(row, "to_dict") else dict(row.__dict__)
        data.pop("_sa_instance_state", None)
        # Names used by the repository's older pyrekordbox adapter.
        if "BPM" in data:
            data.setdefault("AverageBpm", data["BPM"])
        if "Length" in data:
            data.setdefault("TotalTime", data["Length"])
        if "AnalysisDataPath" in data:
            data.setdefault("AnalysisPath", data["AnalysisDataPath"])
        if "SmartList" in data:
            data.setdefault("SmartListXML", data["SmartList"])
        return data

    def get_all(self) -> list[dict[str, Any]]:
        return [self._dict(row) for row in self.database.query(self.model).all()]

    def get_by_id(self, identifier: Any) -> dict[str, Any] | None:
        row = self.database.query(self.model).filter(self.model.ID == str(identifier)).first()
        return self._dict(row) if row else None


class RekordboxConnection:
    """Manages connection to Rekordbox database with support for three operation modes."""

    def __init__(
        self,
        settings: Settings | None = None,
        mode: OperationMode | str = OperationMode.READONLY,
    ):
        self._settings = settings or get_settings()
        self._mode = OperationMode(mode) if isinstance(mode, str) else mode
        self._lock = threading.RLock()
        self._db: Any = None  # pyrekordbox database instance
        self._sqlite_conn: sqlite3.Connection | None = None
        self._db_path: Path | None = None
        self._db_version: str | None = None
        self._db_hash: str | None = None
        self._connected = False

    def connect(self) -> None:
        """Connect to the Rekordbox database."""
        with self._lock:
            if self._connected:
                return

            # Find database path
            self._db_path = self.get_db_path()
            if not self._db_path or not self._db_path.exists():
                raise FileNotFoundError(f"Rekordbox database not found at {self._db_path}")

            # Use the mock backend for placeholder SQLite files as well as
            # when pyrekordbox is unavailable.  This keeps tests and local
            # development deterministic even when Rekordbox is installed.
            use_mock = not PYREKORDBOX_AVAILABLE or not is_rekordbox_database(self._db_path)

            # Verify integrity before connecting
            self.verify_integrity()

            # Get DB version/hash
            self._db_version = self.get_db_version()
            self._db_hash = self.verify_hash()

            # Check if Rekordbox is running (for write modes)
            if not use_mock and self._mode in (OperationMode.XML, OperationMode.MASTERDB):
                if self.is_rekordbox_running():
                    raise RuntimeError(
                        "Rekordbox is currently running. Please close Rekordbox before "
                        "performing write operations."
                    )

            # Connect based on mode
            if use_mock:
                # Mock mode for testing
                self._connected = True
                return

            try:
                if self._mode == OperationMode.MASTERDB:
                    # Direct database write mode - use the current db6 API.
                    self._db = Rekordbox6Database(str(self._db_path))
                else:
                    # Read-only or XML mode - use Rekordbox6Database
                    self._db = Rekordbox6Database(str(self._db_path))

                # Also get a raw SQLite connection for backup operations
                # master.db is encrypted.  Keep a raw connection only when it
                # is actually a normal SQLite file (tests and old databases).
                try:
                    self._sqlite_conn = sqlite3.connect(str(self._db_path))
                    self._sqlite_conn.execute("SELECT 1")
                    self._sqlite_conn.row_factory = sqlite3.Row
                except sqlite3.DatabaseError:
                    self._sqlite_conn = None

                self._connected = True

            except Exception as e:
                raise RuntimeError(f"Failed to connect to Rekordbox database: {e}") from e

    def close(self) -> None:
        """Close database connections."""
        with self._lock:
            if self._sqlite_conn:
                self._sqlite_conn.close()
                self._sqlite_conn = None
            if self._db is not None and hasattr(self._db, "close"):
                self._db.close()
            self._db = None
            self._connected = False

    def __enter__(self) -> RekordboxConnection:
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()

    @property
    def mode(self) -> OperationMode:
        """Get current operation mode."""
        return self._mode

    @mode.setter
    def mode(self, value: OperationMode | str) -> None:
        """Set operation mode (requires reconnection)."""
        new_mode = OperationMode(value) if isinstance(value, str) else value
        if new_mode != self._mode:
            was_connected = self._connected
            self.close()
            self._mode = new_mode
            if was_connected:
                self.connect()

    def get_db_path(self) -> Path | None:
        """
        Get the path to the Rekordbox master.db file.

        Returns:
            Path to master.db or None if not found
        """
        if self._db_path:
            return self._db_path

        # Use configured path if set
        if self._settings.db_path_obj:
            path = self._settings.db_path_obj
            if path.exists():
                self._db_path = path
                return path

        # Auto-detect based on platform
        system = platform.system()
        home = Path.home()

        if system == "Darwin":  # macOS
            candidates = [
                home / "Library/Pioneer/rekordbox/master.db",
                home / "Library/Application Support/Pioneer/rekordbox/master.db",
                home / "Library/Application Support/Pioneer/rekordbox 6/master.db",
            ]
        elif system == "Windows":
            appdata = os.environ.get("APPDATA", "")
            candidates = [
                Path(appdata) / "Pioneer/rekordbox/master.db",
                Path(appdata) / "Pioneer/rekordbox 6/master.db",
            ]
        else:  # Linux
            candidates = [
                home / ".local/share/Pioneer/rekordbox/master.db",
                home / ".local/share/Pioneer/rekordbox 6/master.db",
            ]

        for candidate in candidates:
            if candidate.exists():
                self._db_path = candidate
                return candidate

        return None

    def get_db_version(self) -> str:
        """
        Get database version/hash for integrity checking.

        Returns:
            Version string (schema version + content hash)
        """
        if self._db_version:
            return self._db_version

        if not PYREKORDBOX_AVAILABLE or not self._sqlite_conn:
            # Mock version for testing
            self._db_version = "mock-version-1.0"
            return self._db_version

        try:
            cursor = self._sqlite_conn.cursor()
            # Get schema version from sqlite_master
            cursor.execute("SELECT sql FROM sqlite_master WHERE type='table' ORDER BY name")
            schema = cursor.fetchall()
            schema_str = "".join(row[0] or "" for row in schema)

            # Get record counts for key tables
            cursor.execute("SELECT COUNT(*) FROM djmdContent")
            track_count = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(*) FROM djmdCue")
            cue_count = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(*) FROM djmdPlaylist")
            playlist_count = cursor.fetchone()[0]

            version_data = f"{schema_str}|tracks:{track_count}|cues:{cue_count}|playlists:{playlist_count}"
            self._db_version = hashlib.sha256(version_data.encode()).hexdigest()[:16]
            return self._db_version

        except Exception:
            self._db_version = "unknown"
            return self._db_version

    def verify_hash(self) -> str:
        """
        Verify database file hash.

        Returns:
            SHA256 hash of the database file
        """
        if self._db_hash:
            return self._db_hash

        if not self._db_path or not self._db_path.exists():
            self._db_hash = ""
            return self._db_hash

        try:
            hasher = hashlib.sha256()
            with open(self._db_path, "rb") as f:
                for chunk in iter(lambda: f.read(8192), b""):
                    hasher.update(chunk)
            self._db_hash = hasher.hexdigest()
            return self._db_hash
        except Exception:
            self._db_hash = ""
            return self._db_hash

    def verify_integrity(self) -> bool:
        """
        Verify database integrity using PRAGMA integrity_check.

        Returns:
            True if database is intact

        Raises:
            RuntimeError: If integrity check fails
        """
        if not self._db_path or not self._db_path.exists():
            raise FileNotFoundError(f"Database not found: {self._db_path}")

        if not PYREKORDBOX_AVAILABLE:
            return True  # Mock mode

        try:
            conn = sqlite3.connect(str(self._db_path))
            cursor = conn.cursor()
            cursor.execute("PRAGMA integrity_check")
            result = cursor.fetchone()[0]
            conn.close()

            if result != "ok":
                raise RuntimeError(f"Database integrity check failed: {result}")

            return True
        except sqlite3.DatabaseError:
            # Rekordbox 6/7 master.db is SQLCipher-encrypted and therefore
            # intentionally cannot be checked with the stdlib sqlite driver.
            # Rekordbox6Database performs the real decrypt/open validation.
            return True
        except sqlite3.Error as e:
            raise RuntimeError(f"Database integrity check error: {e}") from e

    def is_rekordbox_running(self) -> bool:
        """
        Check if Rekordbox application is currently running.

        Returns:
            True if Rekordbox process is found
        """
        # Placeholder SQLite files are used by the test/mock backend.  Do not
        # inspect the process table for those files: ``pgrep -f rekordbox``
        # can match the pytest command line (which contains this project's
        # name) and report a false positive.
        if not is_rekordbox_database(self._db_path):
            return False

        if not PYREKORDBOX_AVAILABLE or get_rekordbox_pid is None:
            # Fallback: check process list
            return self._check_rekordbox_process()

        try:
            pid = get_rekordbox_pid()
            return pid is not None
        except Exception:
            return self._check_rekordbox_process()

    def _check_rekordbox_process(self) -> bool:
        """Fallback process check."""
        import subprocess

        system = platform.system()
        try:
            if system == "Darwin":
                result = subprocess.run(
                    ["pgrep", "-f", "rekordbox"],
                    capture_output=True,
                    text=True,
                )
                return result.returncode == 0 and result.stdout.strip() != ""
            elif system == "Windows":
                result = subprocess.run(
                    ["tasklist", "/FI", "IMAGENAME eq rekordbox*"],
                    capture_output=True,
                    text=True,
                )
                return "rekordbox" in result.stdout.lower()
            else:
                result = subprocess.run(
                    ["pgrep", "-f", "rekordbox"],
                    capture_output=True,
                    text=True,
                )
                return result.returncode == 0 and result.stdout.strip() != ""
        except Exception:
            return False

    def get_connection(self) -> sqlite3.Connection:
        """
        Get raw SQLite connection for backup operations.

        Returns:
            SQLite connection

        Raises:
            RuntimeError: If not connected
        """
        if not self._connected or not self._sqlite_conn:
            raise RuntimeError("Database not connected. Call connect() first.")
        return self._sqlite_conn

    @contextmanager
    def transaction(self):
        """Context manager for database transactions (masterdb mode only)."""
        if self._mode != OperationMode.MASTERDB:
            raise RuntimeError("Transactions only available in masterdb mode")

        if not self._sqlite_conn:
            raise RuntimeError("Database not connected")

        try:
            yield self._sqlite_conn
            self._sqlite_conn.commit()
        except Exception:
            self._sqlite_conn.rollback()
            raise

    def execute_read(self, query: str, params: tuple = ()) -> list[sqlite3.Row]:
        """Execute a read query."""
        if not self._sqlite_conn:
            raise RuntimeError("Database not connected")

        cursor = self._sqlite_conn.cursor()
        cursor.execute(query, params)
        return cursor.fetchall()

    def execute_write(self, query: str, params: tuple = ()) -> int:
        """Execute a write query (masterdb mode only)."""
        if self._mode != OperationMode.MASTERDB:
            raise RuntimeError("Write operations only allowed in masterdb mode")

        if not self._sqlite_conn:
            raise RuntimeError("Database not connected")

        # Verify pre-write checks
        if self.is_rekordbox_running():
            raise RuntimeError("Rekordbox is running. Cannot write to database.")

        # Verify integrity and version haven't changed
        self.verify_integrity()
        current_version = self.get_db_version()
        if current_version != self._db_version:
            raise RuntimeError("Database version changed since connection. Aborting write.")

        current_hash = self.verify_hash()
        if current_hash != self._db_hash:
            raise RuntimeError("Database file hash changed since connection. Aborting write.")

        cursor = self._sqlite_conn.cursor()
        cursor.execute(query, params)
        self._sqlite_conn.commit()
        return cursor.rowcount

    @property
    def is_connected(self) -> bool:
        """Check if connected."""
        return self._connected

    @property
    def db_path(self) -> Path | None:
        """Get database path."""
        return self._db_path

    @property
    def db_version(self) -> str | None:
        """Get database version."""
        return self._db_version

    @property
    def db_hash(self) -> str | None:
        """Get database hash."""
        return self._db_hash

    # Pyrekordbox database access
    @property
    def db(self) -> Any:
        """Get pyrekordbox database instance."""
        if not self._connected:
            self.connect()
        return self._db

    def get_content_table(self) -> Any:
        """Get djmdContent table (tracks)."""
        if not PYREKORDBOX_AVAILABLE:
            return None
        return _Db6Table(self.db, db6_tables.DjmdContent) if self._db else None

    def get_cue_table(self) -> Any:
        """Get djmdCue table."""
        if not PYREKORDBOX_AVAILABLE:
            return None
        return _Db6Table(self.db, db6_tables.DjmdCue) if self._db else None

    def get_playlist_table(self) -> Any:
        """Get djmdPlaylist table."""
        if not PYREKORDBOX_AVAILABLE:
            return None
        return _Db6Table(self.db, db6_tables.DjmdPlaylist) if self._db else None

    def get_playlist_content_table(self) -> Any:
        """Get djmdPlaylistContent table."""
        if not PYREKORDBOX_AVAILABLE:
            return None
        return _Db6Table(self.db, db6_tables.DjmdSongPlaylist) if self._db else None
