"""Tests for Rekordbox process detection (``is_rekordbox_running``).

The MCP server's own console scripts (``rekordbox-mcp``, ``rekordbox-webapi``,
``rekordbox-webui``) contain "rekordbox" in their command line, so naive
``pgrep -f rekordbox`` / ``tasklist`` checks report a false positive and block
masterdb writes.  These tests verify that only the Rekordbox desktop
application itself is detected.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pyrekordbox.utils
import pytest

from rekordbox_mcp.db import connection as connection_module
from rekordbox_mcp.db.connection import RekordboxConnection

# Command lines used by the fake subprocess results.
REKORDBOX_APP_MAC = "/Applications/rekordbox 7.app/Contents/MacOS/rekordbox"
REKORDBOX_APP_LINUX = "/opt/rekordbox/rekordbox"
REKORDBOX_APP_WINDOWS = r"C:\Program Files\Pioneer\rekordbox 7\rekordbox.exe"
MCP_SERVER_CMD = "/usr/local/bin/rekordbox-mcp"
WEBAPI_SERVER_CMD = "/usr/local/bin/rekordbox-webapi"


def _make_connection(db_path: Path | None = None) -> RekordboxConnection:
    """Build a connection without running ``__init__`` (only ``_db_path`` is needed)."""
    conn = RekordboxConnection.__new__(RekordboxConnection)
    conn._db_path = db_path
    return conn


def _fake_run_unix(pgrep_stdout: str, ps_cmds: dict[str, str], pgrep_rc: int = 0):
    """Fake ``subprocess.run`` for the macOS/Linux ``pgrep`` + ``ps`` flow."""

    def fake_run(args, **kwargs):
        if args[0] == "pgrep":
            return SimpleNamespace(returncode=pgrep_rc, stdout=pgrep_stdout, stderr="")
        if args[0] == "ps":
            pid = args[2]
            return SimpleNamespace(
                returncode=0,
                stdout=ps_cmds.get(pid, ""),
                stderr="",
            )
        raise AssertionError(f"unexpected subprocess args: {args}")

    return fake_run


def _fake_run_windows(stdout: str, rc: int = 0):
    """Fake ``subprocess.run`` for the Windows PowerShell flow."""

    def fake_run(args, **kwargs):
        if args[0] == "powershell":
            return SimpleNamespace(returncode=rc, stdout=stdout, stderr="")
        raise AssertionError(f"unexpected subprocess args: {args}")

    return fake_run


class TestCheckRekordboxProcess:
    def test_excludes_self_processes_on_macos(self, monkeypatch):
        """rekordbox-mcp / rekordbox-webapi must not count as Rekordbox running."""
        monkeypatch.setattr(connection_module.platform, "system", lambda: "Darwin")
        monkeypatch.setattr(
            connection_module.subprocess,
            "run",
            _fake_run_unix(
                pgrep_stdout="123\n456\n",
                ps_cmds={
                    "123": MCP_SERVER_CMD,
                    "456": WEBAPI_SERVER_CMD,
                },
            ),
        )
        conn = _make_connection()
        assert conn._check_rekordbox_process() is False

    def test_detects_real_app_on_macos(self, monkeypatch):
        """A real Rekordbox app process must be detected."""
        monkeypatch.setattr(connection_module.platform, "system", lambda: "Darwin")
        monkeypatch.setattr(
            connection_module.subprocess,
            "run",
            _fake_run_unix(
                pgrep_stdout="123\n456\n",
                ps_cmds={
                    "123": MCP_SERVER_CMD,
                    "456": REKORDBOX_APP_MAC,
                },
            ),
        )
        conn = _make_connection()
        assert conn._check_rekordbox_process() is True

    def test_excludes_self_processes_on_linux(self, monkeypatch):
        """The Linux branch applies the same exclusion logic."""
        monkeypatch.setattr(connection_module.platform, "system", lambda: "Linux")
        monkeypatch.setattr(
            connection_module.subprocess,
            "run",
            _fake_run_unix(
                pgrep_stdout="123\n456\n",
                ps_cmds={
                    "123": MCP_SERVER_CMD,
                    "456": WEBAPI_SERVER_CMD,
                },
            ),
        )
        conn = _make_connection()
        assert conn._check_rekordbox_process() is False

    def test_detects_real_app_on_linux(self, monkeypatch):
        monkeypatch.setattr(connection_module.platform, "system", lambda: "Linux")
        monkeypatch.setattr(
            connection_module.subprocess,
            "run",
            _fake_run_unix(
                pgrep_stdout="456\n",
                ps_cmds={"456": REKORDBOX_APP_LINUX},
            ),
        )
        conn = _make_connection()
        assert conn._check_rekordbox_process() is True

    def test_excludes_self_processes_on_windows(self, monkeypatch):
        """Windows console scripts (rekordbox-mcp.exe etc.) must be excluded."""
        monkeypatch.setattr(connection_module.platform, "system", lambda: "Windows")
        monkeypatch.setattr(
            connection_module.subprocess,
            "run",
            _fake_run_windows(
                "123|C:\\Python\\Scripts\\rekordbox-mcp.exe\n"
                "456|C:\\Python\\Scripts\\rekordbox-webapi.exe\n"
            ),
        )
        conn = _make_connection()
        assert conn._check_rekordbox_process() is False

    def test_detects_real_app_on_windows(self, monkeypatch):
        monkeypatch.setattr(connection_module.platform, "system", lambda: "Windows")
        monkeypatch.setattr(
            connection_module.subprocess,
            "run",
            _fake_run_windows(
                "123|C:\\Python\\Scripts\\rekordbox-mcp.exe\n"
                f"456|{REKORDBOX_APP_WINDOWS}\n"
            ),
        )
        conn = _make_connection()
        assert conn._check_rekordbox_process() is True

    def test_no_matches_returns_false(self, monkeypatch):
        """pgrep finding nothing must return False."""
        monkeypatch.setattr(connection_module.platform, "system", lambda: "Darwin")
        monkeypatch.setattr(
            connection_module.subprocess,
            "run",
            _fake_run_unix(pgrep_stdout="", ps_cmds={}, pgrep_rc=1),
        )
        conn = _make_connection()
        assert conn._check_rekordbox_process() is False

    def test_excludes_current_process(self, monkeypatch):
        """The current process must never be reported as Rekordbox running."""
        monkeypatch.setattr(connection_module.platform, "system", lambda: "Darwin")
        monkeypatch.setattr(connection_module.os, "getpid", lambda: 999)
        monkeypatch.setattr(
            connection_module.subprocess,
            "run",
            _fake_run_unix(
                pgrep_stdout="999\n",
                ps_cmds={"999": REKORDBOX_APP_MAC},
            ),
        )
        conn = _make_connection()
        assert conn._check_rekordbox_process() is False


class TestIsRekordboxRunning:
    def test_ignores_get_rekordbox_pid_false_positive(self, monkeypatch, tmp_path):
        """is_rekordbox_running must not trust pyrekordbox's get_rekordbox_pid.

        Even when ``get_rekordbox_pid()`` would return a PID (the old false
        positive), the fixed process check must win and report False.
        """
        monkeypatch.setattr(connection_module, "is_rekordbox_database", lambda path: True)
        monkeypatch.setattr(pyrekordbox.utils, "get_rekordbox_pid", lambda: 12345)
        monkeypatch.setattr(connection_module.platform, "system", lambda: "Darwin")
        monkeypatch.setattr(
            connection_module.subprocess,
            "run",
            _fake_run_unix(
                pgrep_stdout="123\n456\n",
                ps_cmds={
                    "123": MCP_SERVER_CMD,
                    "456": WEBAPI_SERVER_CMD,
                },
            ),
        )
        conn = _make_connection(tmp_path / "master.db")
        assert conn.is_rekordbox_running() is False

    def test_returns_true_for_real_app(self, monkeypatch, tmp_path):
        monkeypatch.setattr(connection_module, "is_rekordbox_database", lambda path: True)
        monkeypatch.setattr(connection_module.platform, "system", lambda: "Darwin")
        monkeypatch.setattr(
            connection_module.subprocess,
            "run",
            _fake_run_unix(
                pgrep_stdout="456\n",
                ps_cmds={"456": REKORDBOX_APP_MAC},
            ),
        )
        conn = _make_connection(tmp_path / "master.db")
        assert conn.is_rekordbox_running() is True

    def test_returns_false_for_mock_database(self, monkeypatch, tmp_path):
        """Placeholder (non-Rekordbox) databases skip the process check entirely."""
        monkeypatch.setattr(connection_module, "is_rekordbox_database", lambda path: False)
        monkeypatch.setattr(connection_module.platform, "system", lambda: "Darwin")
        monkeypatch.setattr(
            connection_module.subprocess,
            "run",
            _fake_run_unix(
                pgrep_stdout="456\n",
                ps_cmds={"456": REKORDBOX_APP_MAC},
            ),
        )
        conn = _make_connection(tmp_path / "master.db")
        assert conn.is_rekordbox_running() is False


class TestUseStaticConnection:
    """Regression tests for _use_static_connection().

    Root cause: pyrekordbox's default engine pool for the SQLCipher dialect
    is SingletonThreadPool, which opens a *separate physical connection per
    calling thread*. Since the MCP server dispatches tool calls through
    asyncio.to_thread (whose default executor uses several worker threads),
    a single shared Session ends up mixed across multiple underlying
    connections to the same WAL-mode encrypted file -- reproduced as
    intermittent "disk I/O error" on whichever write happens to land on a
    new thread. _use_static_connection() rebinds the engine to StaticPool
    (one physical connection, reused for every thread) to eliminate this.
    """

    def test_rebinds_to_static_pool(self, tmp_path):
        pytest.importorskip("pyrekordbox")
        from sqlalchemy import create_engine
        from sqlalchemy.orm import Session
        from sqlalchemy.pool import SingletonThreadPool, StaticPool

        from rekordbox_mcp.db.connection import _use_static_connection

        db_path = tmp_path / "plain.db"
        # Mimic pyrekordbox's default pooling for the SQLCipher dialect.
        engine = create_engine(f"sqlite:///{db_path}", poolclass=SingletonThreadPool)
        session = Session(bind=engine)
        session.execute(__import__("sqlalchemy").text("CREATE TABLE t (id INTEGER PRIMARY KEY)"))
        session.commit()

        fake_db = SimpleNamespace(engine=engine, session=session)
        assert isinstance(fake_db.engine.pool, SingletonThreadPool)

        _use_static_connection(fake_db)

        assert isinstance(fake_db.engine.pool, StaticPool)
        # The rebound session/engine must still work.
        fake_db.session.execute(__import__("sqlalchemy").text("SELECT * FROM t"))

    def test_static_pool_survives_cross_thread_access(self, tmp_path):
        """A session rebound to StaticPool must work when queried from
        multiple different threads (serialized by a lock, matching how
        production code guards every _Db6Table call) -- the exact scenario
        that reproduced the disk I/O error with the default
        SingletonThreadPool, where each thread silently got its own separate
        physical connection to the same file underneath one shared Session.
        A lock alone (without StaticPool) does not fix this: it only
        prevents two threads from touching the session at the same instant,
        it does not stop *different* threads from using *different*
        physical connections across successive calls.
        """
        pytest.importorskip("pyrekordbox")
        from sqlalchemy import create_engine, text
        from sqlalchemy.orm import Session
        from sqlalchemy.pool import SingletonThreadPool

        from rekordbox_mcp.db.connection import _use_static_connection

        db_path = tmp_path / "plain2.db"
        engine = create_engine(f"sqlite:///{db_path}", poolclass=SingletonThreadPool)
        session = Session(bind=engine)
        session.execute(text("CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT)"))
        session.commit()

        fake_db = SimpleNamespace(engine=engine, session=session)
        _use_static_connection(fake_db)

        lock = threading.RLock()
        errors = []

        def writer(i):
            try:
                with lock:
                    fake_db.session.execute(text("INSERT INTO t (v) VALUES (:v)"), {"v": f"row{i}"})
                    fake_db.session.commit()
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=writer, args=(i,)) for i in range(5)]
        for th in threads:
            th.start()
        for th in threads:
            th.join()

        assert errors == []
        with lock:
            rows = fake_db.session.execute(text("SELECT COUNT(*) FROM t")).scalar()
        assert rows == 5


class FakeRow:
    """Fake SQLAlchemy row for testing _Db6Table."""

    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)

    def to_dict(self):
        return dict(self.__dict__)


class FakeQuery:
    """Fake SQLAlchemy query for testing _Db6Table."""

    def __init__(self, rows):
        self._rows = rows

    def filter(self, *args, **kwargs):
        return self

    def first(self):
        return self._rows[0] if self._rows else None

    def all(self):
        return self._rows


class FakeDb:
    """Fake pyrekordbox database for testing _Db6Table write operations."""

    def __init__(self):
        self._data: dict[type, dict[str, Any]] = {}
        self._next_id: dict[type, int] = {}
        self._committed = False
        self._commit_count = 0
        self._playlist_songs: dict[str, list[dict]] = {}  # playlist_id -> list of {ContentID, TrackNo, ID}

    def query(self, model):
        return FakeQuery(list(self._data.get(model, {}).values()))

    @staticmethod
    def _is_song_playlist_row(instance) -> bool:
        """True for anything shaped like a DjmdSongPlaylist row.

        connection.py's ``set_tracks()``/``remove_track()`` add and delete
        real ``DjmdSongPlaylist`` ORM instances directly (bypassing
        pyrekordbox's ``add_to_playlist``/``remove_from_playlist`` helpers),
        while this fake also stores playlist-song rows as plain
        :class:`FakeRow` objects for ``add_to_playlist``/``get_playlist_songs``.
        Duck-typing on the playlist-song attributes lets both representations
        share the same ``_playlist_songs`` storage.
        """
        return all(hasattr(instance, attr) for attr in ("PlaylistID", "ContentID", "TrackNo"))

    def add(self, instance):
        if self._is_song_playlist_row(instance):
            pid = str(instance.PlaylistID)
            if not getattr(instance, "ID", None):
                instance.ID = self.generate_unused_id(type(instance))
            entry = {
                "ID": instance.ID,
                "PlaylistID": pid,
                "ContentID": instance.ContentID,
                "TrackNo": instance.TrackNo,
            }
            self._playlist_songs.setdefault(pid, []).append(entry)
            self._playlist_songs[pid].sort(key=lambda s: s["TrackNo"] if s["TrackNo"] is not None else 0)
            return

        model = type(instance)
        if model not in self._data:
            self._data[model] = {}
            self._next_id[model] = 1
        if not hasattr(instance, "ID") or instance.ID is None:
            instance.ID = str(self._next_id[model])
            self._next_id[model] += 1
        self._data[model][str(instance.ID)] = instance

    def delete(self, instance):
        if self._is_song_playlist_row(instance):
            pid = str(instance.PlaylistID)
            song_id = instance.ID
            if pid in self._playlist_songs:
                self._playlist_songs[pid] = [s for s in self._playlist_songs[pid] if s["ID"] != song_id]
            return

        model = type(instance)
        if model in self._data and str(instance.ID) in self._data[model]:
            del self._data[model][str(instance.ID)]

    def commit(self):
        self._committed = True
        self._commit_count += 1

    def flush(self):
        pass

    def generate_unused_id(self, model, is_28_bit=True, id_field_name="ID"):
        if model not in self._next_id:
            self._next_id[model] = 1
        id_val = self._next_id[model]
        self._next_id[model] += 1
        return str(id_val)

    def get_playlist_songs(self, **kwargs):
        playlist_id = kwargs.get("PlaylistID")
        content_id = kwargs.get("ContentID")

        class FakePlaylistSongQuery:
            def __init__(self, songs):
                self._songs = songs

            def all(self):
                return self._songs

        if playlist_id is not None:
            songs = self._playlist_songs.get(str(playlist_id), [])
            if content_id is not None:
                songs = [s for s in songs if s["ContentID"] == content_id]
            # Convert to FakeRow objects
            rows = [FakeRow(**s) for s in songs]
            return FakePlaylistSongQuery(rows)
        return FakePlaylistSongQuery([])

    def add_to_playlist(self, playlist, content, track_no=None):
        playlist_id = str(playlist)
        if playlist_id not in self._playlist_songs:
            self._playlist_songs[playlist_id] = []

        # Determine track_no
        if track_no is None:
            track_no = len(self._playlist_songs[playlist_id]) + 1

        # Shift existing tracks if inserting at a specific position
        if track_no <= len(self._playlist_songs[playlist_id]):
            for s in self._playlist_songs[playlist_id]:
                if s["TrackNo"] >= track_no:
                    s["TrackNo"] += 1

        song_id = self.generate_unused_id(None)
        song = {
            "ID": song_id,
            "PlaylistID": playlist_id,
            "ContentID": content,
            "TrackNo": track_no,
        }
        self._playlist_songs[playlist_id].append(song)
        # Sort by TrackNo
        self._playlist_songs[playlist_id].sort(key=lambda s: s["TrackNo"])
        return FakeRow(**song)

    def remove_from_playlist(self, playlist, song):
        playlist_id = str(playlist)
        if playlist_id in self._playlist_songs:
            # song can be a FakeRow or ID
            song_id = song.ID if hasattr(song, "ID") else song
            self._playlist_songs[playlist_id] = [
                s for s in self._playlist_songs[playlist_id] if s["ID"] != song_id
            ]


class TestDb6TableWriteOperations:
    """Tests for _Db6Table write operations (insert, update, delete, playlist content)."""

    def setup_method(self):
        pytest.importorskip("pyrekordbox")
        from pyrekordbox.db6 import tables as db6_tables
        self.db6_tables = db6_tables

    def test_insert_generates_id_and_commits(self):
        from rekordbox_mcp.db.connection import _Db6Table

        db = FakeDb()
        table = _Db6Table(db, self.db6_tables.DjmdPlaylist)

        record = {"Name": "Test Playlist", "ParentID": "root", "Attribute": 0}
        result = table.insert(record)

        assert result["ID"] is not None
        assert result["Name"] == "Test Playlist"
        assert db._committed is True

    def test_insert_uses_provided_id(self):
        from rekordbox_mcp.db.connection import _Db6Table

        db = FakeDb()
        table = _Db6Table(db, self.db6_tables.DjmdPlaylist)

        # master.db stores playlist IDs as integers; an integer ID is kept as-is.
        record = {"ID": 12345, "Name": "Test Playlist", "ParentID": "root", "Attribute": 0}
        result = table.insert(record)

        assert result["ID"] == 12345

    def test_insert_replaces_non_integer_playlist_id(self):
        """DjmdPlaylist IDs must be integers (pyrekordbox commit() hex-converts
        them); UUID-string IDs from PlaylistManager are replaced with a
        generated integer ID."""
        from rekordbox_mcp.db.connection import _Db6Table

        db = FakeDb()
        table = _Db6Table(db, self.db6_tables.DjmdPlaylist)

        record = {"ID": "custom-id-123", "Name": "Test Playlist", "ParentID": "root", "Attribute": 0}
        result = table.insert(record)

        assert isinstance(result["ID"], int) or str(result["ID"]).isdigit()
        assert result["Name"] == "Test Playlist"

    def test_insert_keeps_non_integer_id_for_other_tables(self):
        """Non-DjmdPlaylist tables (e.g. DjmdCue) keep string IDs."""
        from rekordbox_mcp.db.connection import _Db6Table

        db = FakeDb()
        table = _Db6Table(db, self.db6_tables.DjmdCue)

        record = {"ID": "cue-uuid-abc", "ContentID": 1, "Kind": 0}
        result = table.insert(record)

        assert result["ID"] == "cue-uuid-abc"

    def test_update_modifies_existing_record(self):
        from rekordbox_mcp.db.connection import _Db6Table

        db = FakeDb()
        table = _Db6Table(db, self.db6_tables.DjmdPlaylist)

        # Insert first
        record = {"ID": 12345, "Name": "Old Name", "ParentID": "root", "Attribute": 0}
        table.insert(record)
        db._committed = False

        # Update
        result = table.update(12345, {"Name": "New Name"})

        assert result is not None
        assert result["Name"] == "New Name"
        assert db._committed is True

    def test_update_nonexistent_returns_none(self):
        from rekordbox_mcp.db.connection import _Db6Table

        db = FakeDb()
        table = _Db6Table(db, self.db6_tables.DjmdPlaylist)

        result = table.update("nonexistent", {"Name": "New Name"})

        assert result is None

    def test_delete_removes_record(self):
        from rekordbox_mcp.db.connection import _Db6Table

        db = FakeDb()
        table = _Db6Table(db, self.db6_tables.DjmdPlaylist)

        record = {"ID": 12345, "Name": "Test", "ParentID": "root", "Attribute": 0}
        table.insert(record)
        db._committed = False

        result = table.delete(12345)

        assert result is True
        assert db._committed is True
        assert table.get_by_id(12345) is None

    def test_delete_nonexistent_returns_false(self):
        from rekordbox_mcp.db.connection import _Db6Table

        db = FakeDb()
        table = _Db6Table(db, self.db6_tables.DjmdPlaylist)

        result = table.delete("nonexistent")

        assert result is False

    def test_add_track_appends_to_end(self):
        from rekordbox_mcp.db.connection import _Db6Table

        db = FakeDb()
        table = _Db6Table(db, self.db6_tables.DjmdSongPlaylist)

        result = table.add_track("pl-1", 100)

        assert result is not None
        assert result["PlaylistID"] == "pl-1"
        assert result["ContentID"] == 100
        assert result["TrackNo"] == 1

        tracks = table.get_tracks("pl-1")
        assert tracks == [100]

    def test_add_track_at_position(self):
        from rekordbox_mcp.db.connection import _Db6Table

        db = FakeDb()
        table = _Db6Table(db, self.db6_tables.DjmdSongPlaylist)

        # Add three tracks
        table.add_track("pl-1", 100)  # TrackNo 1
        table.add_track("pl-1", 200)  # TrackNo 2
        table.add_track("pl-1", 300)  # TrackNo 3

        # Insert at position 1 (0-indexed) -> TrackNo 2
        result = table.add_track("pl-1", 999, position=1)

        assert result["TrackNo"] == 2
        tracks = table.get_tracks("pl-1")
        assert tracks == [100, 999, 200, 300]

    def test_remove_track(self):
        from rekordbox_mcp.db.connection import _Db6Table

        db = FakeDb()
        table = _Db6Table(db, self.db6_tables.DjmdSongPlaylist)

        table.add_track("pl-1", 100)
        table.add_track("pl-1", 200)
        table.add_track("pl-1", 300)

        result = table.remove_track("pl-1", 200)

        assert result is True
        tracks = table.get_tracks("pl-1")
        assert tracks == [100, 300]

    def test_remove_nonexistent_track_returns_false(self):
        from rekordbox_mcp.db.connection import _Db6Table

        db = FakeDb()
        table = _Db6Table(db, self.db6_tables.DjmdSongPlaylist)

        table.add_track("pl-1", 100)

        result = table.remove_track("pl-1", 999)

        assert result is False

    def test_set_tracks_replaces_all(self):
        from rekordbox_mcp.db.connection import _Db6Table

        db = FakeDb()
        table = _Db6Table(db, self.db6_tables.DjmdSongPlaylist)

        # Add initial tracks
        table.add_track("pl-1", 100)
        table.add_track("pl-1", 200)

        # Replace with new order
        table.set_tracks("pl-1", [300, 400, 500])

        tracks = table.get_tracks("pl-1")
        assert tracks == [300, 400, 500]

    def test_set_tracks_empty_list_clears_playlist(self):
        from rekordbox_mcp.db.connection import _Db6Table

        db = FakeDb()
        table = _Db6Table(db, self.db6_tables.DjmdSongPlaylist)

        table.add_track("pl-1", 100)
        table.add_track("pl-1", 200)

        table.set_tracks("pl-1", [])

        tracks = table.get_tracks("pl-1")
        assert tracks == []

    def test_set_tracks_replace_commits_exactly_once(self):
        """A replace of an already-populated playlist must be one transaction.

        Regression test: pyrekordbox's ``remove_from_playlist()`` helper
        calls ``commit()`` internally for every removed row. set_tracks()
        used to call it once per existing track, turning a 12-track replace
        into 12+ separate fsync'd write transactions against the
        SQLCipher-encrypted database -- multiplying the chance of a
        transient disk I/O error and leaving the playlist half-updated if a
        later step failed. set_tracks() must now delete/insert directly via
        the session and commit exactly once no matter how many tracks are
        being replaced.
        """
        from rekordbox_mcp.db.connection import _Db6Table

        db = FakeDb()
        table = _Db6Table(db, self.db6_tables.DjmdSongPlaylist)

        for track_id in range(100, 100 + 12):
            table.add_track("pl-1", track_id)
        db._commit_count = 0  # only count commits from the replace itself

        table.set_tracks("pl-1", list(range(500, 512)))

        assert db._commit_count == 1
        assert table.get_tracks("pl-1") == list(range(500, 512))

    def test_remove_track_commits_exactly_once(self):
        from rekordbox_mcp.db.connection import _Db6Table

        db = FakeDb()
        table = _Db6Table(db, self.db6_tables.DjmdSongPlaylist)

        table.add_track("pl-1", 100)
        table.add_track("pl-1", 200)
        table.add_track("pl-1", 300)
        db._commit_count = 0

        result = table.remove_track("pl-1", 200)

        assert result is True
        assert db._commit_count == 1
        assert table.get_tracks("pl-1") == [100, 300]

    def test_concurrent_calls_are_serialized_by_lock(self):
        """_Db6Table must serialize concurrent access to the shared session.

        Regression test: pyrekordbox keeps exactly one SQLAlchemy ``Session``
        per ``Rekordbox6Database``, and it is not thread-safe. The MCP server
        dispatches every tool call through ``asyncio.to_thread``, so two
        overlapping tool calls could previously run on different threads and
        corrupt the shared session concurrently (observed in production as
        ``InvalidRequestError('Session is already flushing')`` immediately
        followed by unrelated "disk I/O error"/"SQL logic error" failures on
        later, single-threaded queries). Every public ``_Db6Table`` method is
        now wrapped with the connection's lock; this test injects an
        artificial delay into a write to prove calls never overlap.
        """
        from rekordbox_mcp.db.connection import _Db6Table

        db = FakeDb()
        lock = threading.RLock()
        table = _Db6Table(db, self.db6_tables.DjmdPlaylist, lock)

        record = {"ID": 1, "Name": "p", "ParentID": "root", "Attribute": 0}
        table.insert(record)

        active = {"count": 0}
        max_concurrent = {"value": 0}
        real_commit = db.commit

        def slow_commit():
            active["count"] += 1
            max_concurrent["value"] = max(max_concurrent["value"], active["count"])
            time.sleep(0.02)
            active["count"] -= 1
            real_commit()

        db.commit = slow_commit

        def writer(i):
            table.update(1, {"Name": f"name-{i}"})

        threads = [threading.Thread(target=writer, args=(i,)) for i in range(5)]
        for th in threads:
            th.start()
        for th in threads:
            th.join()

        assert max_concurrent["value"] == 1

    def test_set_tracks_rolls_back_on_failure(self):
        """A failed replace must roll back instead of leaving a half state."""
        from rekordbox_mcp.db.connection import _Db6Table

        db = FakeDb()
        table = _Db6Table(db, self.db6_tables.DjmdSongPlaylist)
        table.add_track("pl-1", 100)
        table.add_track("pl-1", 200)

        rollback_calls = []
        db.session = SimpleNamespace(rollback=lambda: rollback_calls.append(True))

        def failing_commit():
            raise RuntimeError("disk I/O error")

        db.commit = failing_commit

        with pytest.raises(RuntimeError, match="Failed to set playlist tracks"):
            table.set_tracks("pl-1", [300, 400])

        assert rollback_calls == [True]

    def test_get_tracks_returns_ordered_by_trackno(self):
        from rekordbox_mcp.db.connection import _Db6Table

        db = FakeDb()
        table = _Db6Table(db, self.db6_tables.DjmdSongPlaylist)

        # Add in non-sequential order
        table.add_track("pl-1", 100)  # TrackNo 1
        table.add_track("pl-1", 300)  # TrackNo 2
        table.add_track("pl-1", 200)  # TrackNo 3

        tracks = table.get_tracks("pl-1")
        assert tracks == [100, 300, 200]

    def test_add_track_raises_on_wrong_model(self):
        from rekordbox_mcp.db.connection import _Db6Table

        db = FakeDb()
        table = _Db6Table(db, self.db6_tables.DjmdPlaylist)  # Wrong model

        with pytest.raises(RuntimeError, match="add_track only supported on DjmdSongPlaylist"):
            table.add_track("pl-1", 100)

    def test_remove_track_raises_on_wrong_model(self):
        from rekordbox_mcp.db.connection import _Db6Table

        db = FakeDb()
        table = _Db6Table(db, self.db6_tables.DjmdPlaylist)  # Wrong model

        with pytest.raises(RuntimeError, match="remove_track only supported on DjmdSongPlaylist"):
            table.remove_track("pl-1", 100)

    def test_set_tracks_raises_on_wrong_model(self):
        from rekordbox_mcp.db.connection import _Db6Table

        db = FakeDb()
        table = _Db6Table(db, self.db6_tables.DjmdPlaylist)  # Wrong model

        with pytest.raises(RuntimeError, match="set_tracks only supported on DjmdSongPlaylist"):
            table.set_tracks("pl-1", [100])

    def test_get_tracks_raises_on_wrong_model(self):
        from rekordbox_mcp.db.connection import _Db6Table

        db = FakeDb()
        table = _Db6Table(db, self.db6_tables.DjmdPlaylist)  # Wrong model

        with pytest.raises(RuntimeError, match="get_tracks only supported on DjmdSongPlaylist"):
            table.get_tracks("pl-1")

    def test_insert_with_legacy_field_names(self):
        """Test that insert accepts legacy field names (SmartListXML, AverageBpm, etc.)"""
        from rekordbox_mcp.db.connection import _Db6Table

        db = FakeDb()
        table = _Db6Table(db, self.db6_tables.DjmdPlaylist)

        # Use legacy field names as the repository does
        record = {
            "ID": 12345,
            "Name": "Test Playlist",
            "ParentID": "root",
            "Seq": 0,
            "Attribute": 0,
            "SmartListXML": None,  # Legacy name, model expects SmartList
        }
        result = table.insert(record)

        assert result["ID"] == 12345
        assert result["Name"] == "Test Playlist"
        # The returned dict should have the legacy name
        assert "SmartListXML" in result
        assert result["SmartListXML"] is None

    def test_update_with_legacy_field_names(self):
        """Test that update accepts legacy field names"""
        from rekordbox_mcp.db.connection import _Db6Table

        db = FakeDb()
        table = _Db6Table(db, self.db6_tables.DjmdPlaylist)

        # Insert first
        record = {"ID": 12345, "Name": "Old Name", "ParentID": "root", "Attribute": 0, "SmartListXML": None}
        table.insert(record)
        db._committed = False

        # Update using legacy field name
        result = table.update(12345, {"Name": "New Name", "SmartListXML": "<xml/>"})

        assert result is not None
        assert result["Name"] == "New Name"
        assert result["SmartListXML"] == "<xml/>"
        assert db._committed is True


class TestDiskIOErrorRecovery:
    """A ``disk I/O error`` (e.g. Rekordbox rotating the WAL file under a
    long-lived connection) must close the stale connection so the next
    access reopens fresh file handles, instead of leaving the singleton
    connection stuck returning empty results forever.
    """

    def test_is_disk_io_error_detects_operational_error_message(self):
        assert connection_module.is_disk_io_error(Exception("disk I/O error")) is True
        assert connection_module.is_disk_io_error(
            Exception("(sqlcipher3.dbapi2.OperationalError) disk I/O error"),
        ) is True

    def test_is_disk_io_error_detects_malformed_image(self):
        assert connection_module.is_disk_io_error(
            Exception("database disk image is malformed"),
        ) is True

    def test_is_disk_io_error_ignores_unrelated_errors(self):
        assert connection_module.is_disk_io_error(Exception("no such table: foo")) is False

    def test_recover_from_error_closes_connection_on_disk_io_error(self):
        conn = _make_connection()
        conn._connected = True
        conn._db = object()
        conn._sqlite_conn = None
        conn._lock = threading.RLock()

        recovered = conn.recover_from_error(Exception("disk I/O error"))

        assert recovered is True
        assert conn.is_connected is False
        assert conn._db is None

    def test_recover_from_error_leaves_connection_untouched_for_other_errors(self):
        conn = _make_connection()
        conn._connected = True
        conn._db = object()
        conn._sqlite_conn = None
        conn._lock = threading.RLock()

        recovered = conn.recover_from_error(Exception("no such table: foo"))

        assert recovered is False
        assert conn.is_connected is True