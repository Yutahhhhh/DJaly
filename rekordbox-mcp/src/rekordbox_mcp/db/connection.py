"""Rekordbox database connection management with pyrekordbox integration."""

from __future__ import annotations

import hashlib
import os
import platform
import sqlite3
import subprocess
import threading
from contextlib import contextmanager
from datetime import datetime
from functools import wraps
from pathlib import Path
from typing import Any
from uuid import uuid4

from rekordbox_mcp.config import Settings, get_settings
from rekordbox_mcp.domain.models import OperationMode

# Try to import pyrekordbox.  MasterDatabase was removed from pyrekordbox in
# 0.4.x; Rekordbox6Database is the replacement for both read and write access.
try:
    import pyrekordbox
    from pyrekordbox import Rekordbox6Database
    from pyrekordbox.db6 import tables as db6_tables
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session as SqlAlchemySession
    from sqlalchemy.pool import StaticPool

    PYREKORDBOX_AVAILABLE = True
except ImportError:
    pyrekordbox = None
    Rekordbox6Database = None
    db6_tables = None
    create_engine = None
    SqlAlchemySession = None
    StaticPool = None

# Command-line fragments that identify this project's own processes rather than
# the Rekordbox desktop application.  ``pgrep -f rekordbox`` and
# ``tasklist /FI "IMAGENAME eq rekordbox*"`` match these because the project
# name contains "rekordbox"; they must never be reported as "Rekordbox running".
_SELF_PROCESS_MARKERS = (
    "rekordbox-mcp",
    "rekordbox-webapi",
    "rekordbox-webui",
    "rekordbox_mcp",
)


def is_disk_io_error(exc: Exception) -> bool:
    """Return whether *exc* looks like a transient SQLite/SQLCipher I/O error.

    Errors such as ``disk I/O error`` typically mean the underlying file
    descriptors held by a long-lived connection no longer match the file on
    disk (e.g. Rekordbox or another process checkpointed/rotated the WAL
    file underneath it). The connection object does not recover from this by
    itself, so every subsequent query keeps failing (or, if the caller
    swallows the exception, silently returns empty results) until the
    process is restarted. Callers should close the connection so the next
    access reopens fresh file handles instead.
    """
    message = str(exc).lower()
    return "disk i/o error" in message or "database disk image is malformed" in message


def _locked(method):
    """Serialize a ``_Db6Table`` method call behind ``self._lock``.

    See ``_Db6Table.__init__`` for why this is required: pyrekordbox's
    ``Session`` is shared and not thread-safe, but the MCP server runs every
    tool call through ``asyncio.to_thread``, so overlapping calls can land on
    different threads.
    """

    @wraps(method)
    def wrapper(self, *args, **kwargs):
        with self._lock:
            return method(self, *args, **kwargs)

    return wrapper


def _use_static_connection(db: Any) -> None:
    """Rebind a ``Rekordbox6Database`` instance to a single, shared connection.

    pyrekordbox builds its SQLAlchemy engine with the default pool for a
    file-based SQLite/SQLCipher URL, which is ``SingletonThreadPool``: it
    opens a *separate physical connection per calling OS thread*. The MCP
    server dispatches every tool call through ``asyncio.to_thread``, whose
    default executor uses a pool of several worker threads, so a
    ``RekordboxConnection``'s single shared SQLAlchemy ``Session`` ends up
    being used with a *different* underlying SQLCipher connection depending
    on which thread happened to run a given call -- even with calls fully
    serialized by a lock. Mixing physical connections underneath one ORM
    Session's identity map corrupts its view of the WAL-mode encrypted
    database and surfaces as intermittent ``disk I/O error`` / ``SQL logic
    error`` on whichever call happens to run next, exactly matching the
    observed "first write after reconnect succeeds, second write fails"
    pattern (each write landing on a different thread pool worker).

    Rebinding to ``StaticPool`` (one physical connection, shared safely
    across threads since access is already serialized by
    ``RekordboxConnection._lock``) eliminates the thread-to-connection
    proliferation entirely, regardless of which thread happens to call in.
    """
    if create_engine is None or StaticPool is None or SqlAlchemySession is None:
        return

    old_engine = db.engine
    new_engine = create_engine(
        old_engine.url,
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    if db.session is not None:
        db.session.close()
    old_engine.dispose()
    db.engine = new_engine
    db.session = SqlAlchemySession(bind=new_engine)


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
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='djmdContent'",
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

    This class also provides write operations for masterdb mode using
    pyrekordbox 0.4.4's Rekordbox6Database API.
    """

    def __init__(self, database: Any, model: Any, lock: threading.RLock | None = None):
        self.database = database
        self.model = model
        # SQLAlchemy's ``Session`` (pyrekordbox keeps exactly one, shared for
        # the whole ``Rekordbox6Database`` instance) is not thread-safe.  The
        # MCP server dispatches every tool call through ``asyncio.to_thread``,
        # so two overlapping tool calls can run on different threads and
        # touch the same session concurrently. That produces SQLAlchemy
        # errors like "Session is already flushing" and, once the session's
        # internal state is corrupted, the underlying SQLCipher connection
        # starts raising nonsensical low-level errors ("disk I/O error",
        # "SQL logic error") for unrelated, later, single-threaded queries.
        # Every public method below acquires this lock (shared with the
        # owning ``RekordboxConnection``) so only one thread ever touches the
        # session/connection at a time.
        self._lock = lock or threading.RLock()
        # Cache for foreign-key -> display-name lookups (per (model, id)).
        self._name_cache: dict[tuple[Any, str], str | None] = {}

    # Forward mapping: DB field name -> legacy field name (for reading)
    _FORWARD_FIELD_MAP = {
        "BPM": "AverageBpm",
        "Length": "TotalTime",
        "AnalysisDataPath": "AnalysisPath",
        "SmartList": "SmartListXML",
    }

    # Reverse mapping: legacy field name -> DB field name (for writing)
    _REVERSE_FIELD_MAP = {
        "AverageBpm": "BPM",
        "TotalTime": "Length",
        "AnalysisPath": "AnalysisDataPath",
        "SmartListXML": "SmartList",
    }

    def _dict(self, row: Any) -> dict[str, Any]:
        data = row.to_dict() if hasattr(row, "to_dict") else dict(row.__dict__)
        data.pop("_sa_instance_state", None)
        # Names used by the repository's older pyrekordbox adapter.
        for db_field, legacy_field in self._FORWARD_FIELD_MAP.items():
            if db_field in data:
                data.setdefault(legacy_field, data[db_field])
        # pyrekordbox 0.4.x stores Artist/Genre/Key as foreign-key IDs on
        # DjmdContent; resolve them to display names so the repository can
        # read Artist/Genre/Key directly.
        self._resolve_fk_names(data)
        return data

    def _to_model_kwargs(self, record: dict[str, Any]) -> dict[str, Any]:
        """Convert legacy field names to model field names for insertion/update."""
        result = dict(record)
        for legacy_field, db_field in self._REVERSE_FIELD_MAP.items():
            if legacy_field in result:
                result[db_field] = result.pop(legacy_field)
        return result

    def _resolve_fk_names(self, data: dict[str, Any]) -> None:
        """Resolve DjmdContent foreign-key IDs (ArtistID/GenreID/KeyID) to names."""
        if db6_tables is None:
            return
        if data.get("ArtistID") is not None and "Artist" not in data:
            name = self._lookup_name(db6_tables.DjmdArtist, data["ArtistID"], "Name")
            if name:
                data["Artist"] = name
        if data.get("GenreID") is not None and "Genre" not in data:
            name = self._lookup_name(db6_tables.DjmdGenre, data["GenreID"], "Name")
            if name:
                data["Genre"] = name
        if data.get("KeyID") is not None and "Key" not in data:
            name = self._lookup_name(db6_tables.DjmdKey, data["KeyID"], "ScaleName")
            if name:
                data["Key"] = name

    def _lookup_name(self, model: Any, id_val: Any, name_col: str) -> str | None:
        """Look up a display name for a foreign-key ID, or None when missing."""
        key = (model, str(id_val))
        if key not in self._name_cache:
            try:
                row = self.database.query(model).filter(str(id_val) == model.ID).first()
                self._name_cache[key] = str(getattr(row, name_col)) if row is not None else None
            except Exception:
                self._name_cache[key] = None
        return self._name_cache[key]

    @_locked
    def get_all(self) -> list[dict[str, Any]]:
        return [self._dict(row) for row in self.database.query(self.model).all()]

    @_locked
    def get_by_id(self, identifier: Any) -> dict[str, Any] | None:
        row = self.database.query(self.model).filter(str(identifier) == self.model.ID).first()
        return self._dict(row) if row else None

    # =========================================================================
    # Write operations (masterdb mode only)
    # =========================================================================

    @_locked
    def insert(self, record: dict[str, Any]) -> dict[str, Any]:
        """Insert a new record. Generates ID if not provided."""
        if db6_tables is None:
            raise RuntimeError("pyrekordbox not available")

        # Convert legacy field names to model field names
        model_kwargs = self._to_model_kwargs(record)

        # Rekordbox master.db stores playlist IDs as 28-bit integers and
        # pyrekordbox 0.4.x commit() converts them to hex (int(playlist_id)).
        # UUID-string IDs (used by PlaylistManager) must therefore be replaced
        # with a generated integer ID for the DjmdPlaylist table.
        if self.model is db6_tables.DjmdPlaylist:
            raw_id = model_kwargs.get("ID")
            if raw_id is None or not isinstance(raw_id, int):
                model_kwargs["ID"] = self.database.generate_unused_id(self.model)

        # Generate ID if not present
        if "ID" not in model_kwargs or model_kwargs["ID"] is None:
            model_kwargs["ID"] = self.database.generate_unused_id(self.model)

        # Create model instance
        instance = self.model(**model_kwargs)
        self.database.add(instance)
        # Flush so SQLAlchemy populates default columns (updated_at etc.)
        # before we sync masterPlaylists6.xml.
        self.database.flush()

        # Keep masterPlaylists6.xml in sync for new playlists so Rekordbox
        # shows them after the next launch (and commit() does not warn about
        # a playlist missing from the XML).
        if self.model is db6_tables.DjmdPlaylist and getattr(
            self.database, "playlist_xml", None,
        ) is not None:
            try:
                self.database.playlist_xml.add(
                    playlist_id=instance.ID,
                    parent_id=instance.ParentID,
                    attribute=instance.Attribute,
                    updated_at=instance.updated_at,
                )
                self.database.playlist_xml.save()
            except Exception:
                pass

        self.database.commit()

        return self._dict(instance)

    @_locked
    def update(self, id_val: Any, updates: dict[str, Any]) -> dict[str, Any] | None:
        """Update a record by ID."""
        if db6_tables is None:
            raise RuntimeError("pyrekordbox not available")

        row = self.database.query(self.model).filter(str(id_val) == self.model.ID).first()
        if row is None:
            return None

        # Convert legacy field names to model field names
        model_updates = self._to_model_kwargs(updates)

        for key, value in model_updates.items():
            setattr(row, key, value)

        self.database.commit()

        # Keep masterPlaylists6.xml in sync when updating a playlist.
        if self.model is db6_tables.DjmdPlaylist and getattr(
            self.database, "playlist_xml", None,
        ) is not None:
            try:
                self.database.playlist_xml.update(
                    playlist_id=row.ID,
                    parent_id=row.ParentID,
                    attribute=row.Attribute,
                    updated_at=row.updated_at,
                )
                self.database.playlist_xml.save()
            except Exception:
                pass

        return self._dict(row)

    @_locked
    def delete(self, id_val: Any) -> bool:
        """Delete a record by ID."""
        if db6_tables is None:
            raise RuntimeError("pyrekordbox not available")

        row = self.database.query(self.model).filter(str(id_val) == self.model.ID).first()
        if row is None:
            return False

        self.database.delete(row)
        self.database.commit()

        # Keep masterPlaylists6.xml in sync when deleting a playlist.
        if self.model is db6_tables.DjmdPlaylist and getattr(
            self.database, "playlist_xml", None,
        ) is not None:
            try:
                self.database.playlist_xml.remove(str(id_val))
                self.database.playlist_xml.save()
            except Exception:
                pass

        return True

    # Playlist content (DjmdSongPlaylist) specific methods
    @_locked
    def add_track(self, playlist_id: str, track_id: int, position: int | None = None) -> dict[str, Any] | None:
        """Add a track to a playlist at the given position (0-indexed)."""
        if db6_tables is None:
            raise RuntimeError("pyrekordbox not available")

        if self.model is not db6_tables.DjmdSongPlaylist:
            raise RuntimeError("add_track only supported on DjmdSongPlaylist table")

        # pyrekordbox uses 1-based TrackNo; position is 0-indexed
        track_no = (position + 1) if position is not None else None

        try:
            result = self.database.add_to_playlist(
                playlist=playlist_id,
                content=track_id,
                track_no=track_no,
            )
            # add_to_playlist() only stages the change via session.add(); it
            # does not commit (unlike pyrekordbox's remove_from_playlist()).
            # Without an explicit commit here, the row stays pending in the
            # shared session and is only persisted incidentally if some other
            # unrelated commit() happens to run later -- or lost entirely.
            self.database.commit()
            return self._dict(result) if result else None
        except Exception as e:
            try:
                self.database.session.rollback()
            except Exception:
                pass
            raise RuntimeError(f"Failed to add track to playlist: {e}") from e

    @_locked
    def remove_track(self, playlist_id: str, track_id: int) -> bool:
        """Remove a track from a playlist."""
        if db6_tables is None:
            raise RuntimeError("pyrekordbox not available")

        if self.model is not db6_tables.DjmdSongPlaylist:
            raise RuntimeError("remove_track only supported on DjmdSongPlaylist table")

        try:
            # Find the DjmdSongPlaylist row for this playlist/track combination
            rows = self.database.get_playlist_songs(PlaylistID=str(playlist_id), ContentID=track_id).all()
            if not rows:
                return False

            # Delete directly via the session instead of pyrekordbox's
            # ``remove_from_playlist()`` helper, which calls ``self.commit()``
            # (a full fsync'd write transaction, a scan of every playlist for
            # the XML sync, and a possible masterPlaylists6.xml rewrite) once
            # per removed row. A single row is normally fine, but doing this
            # consistently with set_tracks() keeps the whole operation to one
            # commit and avoids the same amplification if duplicates exist.
            for row in rows:
                self.database.delete(row)
            self._renumber_after_removal(playlist_id, rows)
            self.database.commit()
            return True
        except Exception as e:
            try:
                self.database.session.rollback()
            except Exception:
                pass
            raise RuntimeError(f"Failed to remove track from playlist: {e}") from e

    def _renumber_after_removal(self, playlist_id: str, removed_rows: list[Any]) -> None:
        """Shift TrackNo down for rows after each removed row's position."""
        removed_nos = sorted(
            {row.TrackNo for row in removed_rows if row.TrackNo is not None},
        )
        if not removed_nos:
            return
        remaining = self.database.get_playlist_songs(PlaylistID=str(playlist_id)).all()
        for row in remaining:
            if row.TrackNo is None:
                continue
            shift = sum(1 for no in removed_nos if no < row.TrackNo)
            if shift:
                row.TrackNo -= shift

    @_locked
    def set_tracks(self, playlist_id: str, track_ids: list[int]) -> None:
        """Replace all tracks in a playlist with the given ordered list.

        Deletes and re-inserts ``DjmdSongPlaylist`` rows directly through the
        SQLAlchemy session and commits exactly once. pyrekordbox's
        ``remove_from_playlist()``/``add_to_playlist()`` helpers were used
        previously, but ``remove_from_playlist()`` calls ``self.commit()``
        internally for *every* removed row -- turning a single logical
        "replace" into N+1 separate fsync'd write transactions against the
        SQLCipher-encrypted database (each also re-scanning every playlist
        for the masterPlaylists6.xml sync). That amplification made large
        replacements far more likely to hit a transient disk I/O error, and
        because each removal was already permanently committed, a failure
        partway through left the playlist in a half-deleted state instead of
        rolling back cleanly.
        """
        if db6_tables is None:
            raise RuntimeError("pyrekordbox not available")

        if self.model is not db6_tables.DjmdSongPlaylist:
            raise RuntimeError("set_tracks only supported on DjmdSongPlaylist table")

        try:
            existing_rows = self.database.get_playlist_songs(PlaylistID=str(playlist_id)).all()
            for row in existing_rows:
                self.database.delete(row)

            now = datetime.now()
            for idx, track_id in enumerate(track_ids):
                song = db6_tables.DjmdSongPlaylist.create(
                    ID=str(uuid4()),
                    PlaylistID=str(playlist_id),
                    ContentID=str(track_id),
                    TrackNo=idx + 1,  # 1-based
                    UUID=str(uuid4()),
                    created_at=now,
                    updated_at=now,
                )
                self.database.add(song)

            self.database.commit()
        except Exception as e:
            try:
                self.database.session.rollback()
            except Exception:
                pass
            raise RuntimeError(f"Failed to set playlist tracks: {e}") from e

    @_locked
    def get_tracks(self, playlist_id: str) -> list[int]:
        """Get track IDs in a playlist in TrackNo order."""
        if db6_tables is None:
            raise RuntimeError("pyrekordbox not available")

        if self.model is not db6_tables.DjmdSongPlaylist:
            raise RuntimeError("get_tracks only supported on DjmdSongPlaylist table")

        try:
            rows = self.database.get_playlist_songs(PlaylistID=str(playlist_id)).all()
            rows.sort(key=lambda row: (row.TrackNo is None, row.TrackNo or 0))
            return [int(row.ContentID) for row in rows if row.ContentID is not None]
        except Exception as e:
            raise RuntimeError(f"Failed to get playlist tracks: {e}") from e


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
        self._db_unavailable = False
        self._unavailable_reason: str | None = None

    def connect(self) -> None:
        """Connect to the Rekordbox database.

        When no Rekordbox database can be found the connection is left in a
        "not connected" state instead of raising.  The reason is recorded in
        ``db_unavailable_reason`` so callers (server startup, tools, status)
        can fail gracefully instead of crashing the process.
        """
        with self._lock:
            if self._connected:
                return

            # Find database path
            self._db_path = self.get_db_path()
            if not self._db_path or not self._db_path.exists():
                self._db_unavailable = True
                self._unavailable_reason = (
                    f"Rekordbox database not found at {self._db_path}"
                    if self._db_path
                    else "Rekordbox database not found (auto-detection found no master.db)"
                )
                return

            self._db_unavailable = False
            self._unavailable_reason = None

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
                        "performing write operations.",
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

                # See _use_static_connection(): must run immediately, before
                # any query/commit touches the default SingletonThreadPool
                # engine pyrekordbox just created.
                _use_static_connection(self._db)

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

    def recover_from_error(self, exc: Exception) -> bool:
        """Close the connection if *exc* looks like a disk I/O error.

        Returns True when the connection was closed (the next ``.db``/
        ``get_connection()`` access will transparently reopen it), False
        otherwise. This must be called from the ``except`` block of any code
        path that queries the database, so a transient I/O error does not
        leave this singleton connection permanently stuck returning failures
        or empty results.
        """
        if is_disk_io_error(exc):
            self.close()
            return True
        return False

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
            self._db_unavailable = False
            self._unavailable_reason = None

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
            True if database is intact, False if the database file is missing
            (the connection is marked unavailable in that case).

        Raises:
            RuntimeError: If integrity check fails
        """
        if not self._db_path or not self._db_path.exists():
            self._db_unavailable = True
            self._unavailable_reason = (
                f"Rekordbox database not found at {self._db_path}"
                if self._db_path
                else "Rekordbox database not found (auto-detection found no master.db)"
            )
            return False

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
        Check if the Rekordbox application is currently running.

        Only the Rekordbox desktop application counts.  pyrekordbox's
        ``get_rekordbox_pid()`` matches any process whose name is "rekordbox",
        which includes this server's own console scripts (``rekordbox-mcp``,
        ``rekordbox-webapi``), so it is deliberately not used here.  The
        process check below inspects each candidate's command line and filters
        those processes out.

        Returns:
            True if the Rekordbox application process is found
        """
        # Placeholder SQLite files are used by the test/mock backend.  Do not
        # inspect the process table for those files: ``pgrep -f rekordbox``
        # can match the pytest command line (which contains this project's
        # name) and report a false positive.
        if not is_rekordbox_database(self._db_path):
            return False

        return self._check_rekordbox_process()

    def _check_rekordbox_process(self) -> bool:
        """Check whether the Rekordbox desktop application is running.

        ``pgrep -f rekordbox`` matches the full command line, so it also
        matches this server's own processes (``rekordbox-mcp``,
        ``rekordbox-webapi``, ``rekordbox-webui``) as well as unrelated
        processes that merely mention "rekordbox" somewhere in their
        arguments (e.g. an MCP orchestrator process whose command line lists
        tool names like ``rekordbox_add_tracks_to_playlist``). It is only
        used to gather *candidate* PIDs; each candidate is then confirmed by
        inspecting its actual executable name (not its arguments) so that
        only the real Rekordbox.app process counts.
        """
        system = platform.system()
        try:
            if system == "Windows":
                return self._check_rekordbox_process_windows()
            result = subprocess.run(
                ["pgrep", "-f", "rekordbox"],
                capture_output=True,
                text=True,
            )
            if result.returncode != 0 or not result.stdout.strip():
                return False
            for pid in result.stdout.split():
                if self._is_rekordbox_app_pid(pid):
                    return True
            return False
        except Exception:
            return False

    def _is_rekordbox_app_pid(self, pid: str) -> bool:
        """Return True when *pid* belongs to the Rekordbox application itself."""
        if pid.isdigit() and int(pid) == os.getpid():
            return False
        result = subprocess.run(
            ["ps", "-p", pid, "-o", "comm="],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            return False
        return self._is_rekordbox_app_comm(result.stdout)

    def _is_rekordbox_app_comm(self, comm: str) -> bool:
        """Return True when *comm* is the Rekordbox application executable.

        ``comm`` (``ps -o comm=``) is the process's executable path, not its
        argument list. Matching only the executable's basename avoids false
        positives from processes that merely mention "rekordbox" in their
        arguments; the real Rekordbox.app binary is named exactly
        "rekordbox" (case-insensitive).
        """
        basename = comm.strip().rsplit("/", 1)[-1].lower()
        if basename in _SELF_PROCESS_MARKERS:
            return False
        return basename == "rekordbox"

    def _check_rekordbox_process_windows(self) -> bool:
        """Windows process check using PowerShell command lines.

        ``tasklist /FI "IMAGENAME eq rekordbox*"`` matches this project's own
        console scripts (``rekordbox-mcp.exe`` etc.) as well as the Rekordbox
        application, and tasklist does not expose command lines.  PowerShell's
        ``Get-CimInstance`` provides both PID and command line so the same
        exclusion logic can be applied.
        """
        ps_cmd = (
            "Get-CimInstance Win32_Process -Filter \"Name like 'rekordbox%'\" | "
            "ForEach-Object { $_.ProcessId.ToString() + '|' + $_.CommandLine }"
        )
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps_cmd],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0 or not result.stdout.strip():
            return False
        for line in result.stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            if "|" in line:
                pid, cmdline = line.split("|", 1)
                if pid.isdigit() and int(pid) == os.getpid():
                    continue
            else:
                cmdline = line
            if self._is_rekordbox_app_cmdline(cmdline):
                return True
        return False

    def _is_rekordbox_app_cmdline(self, cmdline: str) -> bool:
        """Return True when a Windows command line belongs to the Rekordbox app.

        Only used by the Windows check, which already scopes candidates to
        processes whose image name starts with "rekordbox" (see
        ``Get-CimInstance ... -Filter "Name like 'rekordbox%'"``), so a
        cmdline substring check does not have the same false-positive risk
        as the macOS/Linux ``pgrep -f rekordbox`` path.
        """
        lowered = cmdline.lower()
        if any(marker in lowered for marker in _SELF_PROCESS_MARKERS):
            return False
        return "rekordbox" in lowered

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
    def db_unavailable_reason(self) -> str | None:
        """Reason the Rekordbox database is unavailable, or None if available."""
        return self._unavailable_reason

    def ensure_available(self) -> None:
        """Raise a clear error when the Rekordbox database is unavailable.

        Callers that need the database (repository methods, tools) use this to
        fail with an actionable message instead of silently returning empty
        results or crashing the process.
        """
        if self._db_unavailable:
            raise RuntimeError(
                f"Rekordbox database not available: {self._unavailable_reason}",
            )

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
        # Access ``self.db`` (the property) first: it transparently reconnects
        # when ``recover_from_error`` has closed the connection after a disk
        # I/O error. Checking the raw ``self._db`` attribute instead would
        # see the post-close ``None`` and return None forever, without ever
        # triggering the reconnect.
        db = self.db
        return _Db6Table(db, db6_tables.DjmdContent, self._lock) if db else None

    def get_cue_table(self) -> Any:
        """Get djmdCue table."""
        if not PYREKORDBOX_AVAILABLE:
            return None
        db = self.db
        return _Db6Table(db, db6_tables.DjmdCue, self._lock) if db else None

    def get_playlist_table(self) -> Any:
        """Get djmdPlaylist table."""
        if not PYREKORDBOX_AVAILABLE:
            return None
        db = self.db
        return _Db6Table(db, db6_tables.DjmdPlaylist, self._lock) if db else None

    def get_playlist_content_table(self) -> Any:
        """Get djmdPlaylistContent table."""
        if not PYREKORDBOX_AVAILABLE:
            return None
        db = self.db
        return _Db6Table(db, db6_tables.DjmdSongPlaylist, self._lock) if db else None
