"""Tests for track search/detail MCP tools.

Uses the built-in mock database backend (see test_mcp_tools.py): pyrekordbox
is not required for these tests, and the mock library contains two tracks
(Mock Track 1 / House / 128 BPM, Mock Track 2 / Techno / 124 BPM) plus the
playlist "pl1" containing [1, 2].
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from rekordbox_mcp.config import Settings
from rekordbox_mcp.domain.models import OperationMode
from rekordbox_mcp.mcp import server as mcp_server

# Ensure the FastMCP server + all tool modules are created/registered exactly once,
# before importing individual tool functions.
mcp_server.create_mcp_server()

from rekordbox_mcp.mcp.tools_track import (  # noqa: E402
    get_playlist_tracks_with_details,
    get_track,
    search_tracks,
)


@pytest.fixture
def db_file(tmp_path: Path) -> Path:
    """A dummy sqlite file that satisfies RekordboxConnection's existence check."""
    path = tmp_path / "master.db"
    conn = sqlite3.connect(path)
    conn.close()
    return path


@pytest.fixture
def mcp_settings(tmp_path: Path, db_file: Path) -> Settings:
    settings = Settings(
        db_path=str(db_file),
        backup_dir=str(tmp_path / "backups"),
        mode="readonly",
    )
    settings.mode = OperationMode.READONLY
    return settings


@pytest.fixture
def readonly_services(mcp_settings: Settings):
    mcp_server.cleanup_services()
    mcp_server.initialize_services(mcp_settings, OperationMode.READONLY)
    mcp_server.get_repository().connect()
    yield
    mcp_server.cleanup_services()


@pytest.fixture
def no_db_settings(tmp_path: Path) -> Settings:
    """Settings pointing at a master.db that does not exist anywhere."""
    settings = Settings(
        db_path=str(tmp_path / "missing" / "master.db"),
        backup_dir=str(tmp_path / "backups"),
        mode="readonly",
    )
    settings.mode = OperationMode.READONLY
    return settings


@pytest.fixture
def unavailable_services(no_db_settings: Settings, monkeypatch):
    """Services initialized in an environment with no Rekordbox database."""
    from rekordbox_mcp.db.connection import RekordboxConnection

    monkeypatch.setattr(RekordboxConnection, "get_db_path", lambda self: None)
    mcp_server.cleanup_services()
    mcp_server.initialize_services(no_db_settings, OperationMode.READONLY)
    yield
    mcp_server.cleanup_services()


class TestSearchTracks:
    async def test_search_by_title_partial_match(self, readonly_services):
        result = await search_tracks(query="Track 1")

        assert len(result) == 1
        assert result[0]["id"] == 1
        assert result[0]["title"] == "Mock Track 1"
        assert result[0]["artist"] == "Mock Artist 1"
        assert result[0]["bpm"] == pytest.approx(128.0)
        assert result[0]["key"] == "5A"
        assert result[0]["genre"] == "House"

    async def test_search_by_artist_partial_match(self, readonly_services):
        result = await search_tracks(query="artist 2")

        assert len(result) == 1
        assert result[0]["id"] == 2
        assert result[0]["artist"] == "Mock Artist 2"

    async def test_search_is_case_insensitive(self, readonly_services):
        result = await search_tracks(query="MOCK TRACK")

        assert {t["id"] for t in result} == {1, 2}

    async def test_search_genre_filter(self, readonly_services):
        result = await search_tracks(query="Mock", genre="House")

        assert [t["id"] for t in result] == [1]

    async def test_search_min_bpm_filter(self, readonly_services):
        result = await search_tracks(query="Mock", min_bpm=125.0)

        assert [t["id"] for t in result] == [1]

    async def test_search_max_bpm_filter(self, readonly_services):
        result = await search_tracks(query="Mock", max_bpm=125.0)

        assert [t["id"] for t in result] == [2]

    async def test_search_combined_filters(self, readonly_services):
        result = await search_tracks(query="Mock", genre="Techno", min_bpm=120.0, max_bpm=130.0)

        assert [t["id"] for t in result] == [2]

    async def test_search_limit(self, readonly_services):
        result = await search_tracks(query="Mock", limit=1)

        assert len(result) == 1

    async def test_search_no_match_returns_empty_list(self, readonly_services):
        result = await search_tracks(query="nonexistent")

        assert result == []


class TestGetTrack:
    async def test_get_track_returns_details(self, readonly_services):
        result = await get_track(track_id=1)

        assert result["id"] == 1
        assert result["title"] == "Mock Track 1"
        assert result["artist"] == "Mock Artist 1"
        assert result["bpm"] == pytest.approx(128.0)
        assert result["key"] == "5A"
        assert result["genre"] == "House"
        # Mock track 1 has TotalTime = 300000 ms -> 300.0 seconds.
        assert result["duration"] == pytest.approx(300.0)

    async def test_get_track_not_found(self, readonly_services):
        result = await get_track(track_id=999)

        assert result["success"] is False
        assert "not found" in result["error"]


class TestGetPlaylistTracksWithDetails:
    async def test_returns_tracks_in_order_with_details(self, readonly_services):
        result = await get_playlist_tracks_with_details(playlist_id="pl1")

        assert result["playlist_id"] == "pl1"
        assert result["playlist_name"] == "My Playlist"
        assert [t["id"] for t in result["tracks"]] == [1, 2]
        assert result["tracks"][0]["title"] == "Mock Track 1"
        assert result["tracks"][0]["genre"] == "House"
        assert result["tracks"][1]["title"] == "Mock Track 2"
        assert result["tracks"][1]["genre"] == "Techno"

    async def test_missing_playlist_returns_empty(self, readonly_services):
        result = await get_playlist_tracks_with_details(playlist_id="nope")

        assert result["playlist_name"] is None
        assert result["tracks"] == []


class TestTrackToolsWithoutDb:
    async def test_search_tracks_graceful_error(self, unavailable_services):
        result = await search_tracks(query="Mock")

        assert result["success"] is False
        assert "not available" in result["error"].lower()

    async def test_get_track_graceful_error(self, unavailable_services):
        result = await get_track(track_id=1)

        assert result["success"] is False
        assert "not available" in result["error"].lower()

    async def test_get_playlist_tracks_with_details_graceful_error(self, unavailable_services):
        result = await get_playlist_tracks_with_details(playlist_id="pl1")

        assert result["success"] is False
        assert "not available" in result["error"].lower()


class TestDb6TableFkResolution:
    """pyrekordbox 0.4.x stores Artist/Genre/Key as FK IDs on DjmdContent.

    ``_Db6Table._dict`` must resolve those IDs to display names so the
    repository's ``_row_to_track`` can read Artist/Genre/Key directly.
    """

    def test_resolves_artist_genre_key_fk_ids(self):
        pytest.importorskip("pyrekordbox")
        from pyrekordbox.db6 import tables as db6_tables

        from rekordbox_mcp.db.connection import _Db6Table

        class FakeRow:
            def __init__(self, **kwargs):
                self.__dict__.update(kwargs)

            def to_dict(self):
                return dict(self.__dict__)

        class FakeQuery:
            def __init__(self, rows):
                self._rows = rows

            def filter(self, *args, **kwargs):
                return self

            def first(self):
                return self._rows[0] if self._rows else None

        class FakeDb:
            def __init__(self, rows_by_model):
                self._rows = rows_by_model

            def query(self, model):
                return FakeQuery(self._rows.get(model, []))

        db = FakeDb(
            {
                db6_tables.DjmdArtist: [FakeRow(ID="1", Name="Daft Punk")],
                db6_tables.DjmdGenre: [FakeRow(ID="2", Name="House")],
                db6_tables.DjmdKey: [FakeRow(ID="3", ScaleName="5A")],
            },
        )
        table = _Db6Table(db, db6_tables.DjmdContent)
        row = FakeRow(
            ID=123,
            Title="One More Time",
            ArtistID="1",
            GenreID="2",
            KeyID="3",
            BPM=12300,
            Length=300000,
            AnalysisDataPath="/x/1.anlz",
        )

        data = table._dict(row)

        assert data["Artist"] == "Daft Punk"
        assert data["Genre"] == "House"
        assert data["Key"] == "5A"
        # Legacy column-name aliases must still be applied.
        assert data["AverageBpm"] == 12300
        assert data["TotalTime"] == 300000
        assert data["AnalysisPath"] == "/x/1.anlz"

    def test_missing_fk_target_leaves_field_unset(self):
        pytest.importorskip("pyrekordbox")
        from pyrekordbox.db6 import tables as db6_tables

        from rekordbox_mcp.db.connection import _Db6Table

        class FakeRow:
            def __init__(self, **kwargs):
                self.__dict__.update(kwargs)

            def to_dict(self):
                return dict(self.__dict__)

        class FakeQuery:
            def filter(self, *args, **kwargs):
                return self

            def first(self):
                return None

        class FakeDb:
            def query(self, model):
                return FakeQuery()

        table = _Db6Table(FakeDb(), db6_tables.DjmdContent)
        row = FakeRow(ID=123, Title="Orphan", ArtistID="999", GenreID="999", KeyID="999")

        data = table._dict(row)

        assert "Artist" not in data
        assert "Genre" not in data
        assert "Key" not in data
