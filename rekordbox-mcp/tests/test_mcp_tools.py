"""Tests for MCP tool functions using the built-in mock database backend.

pyrekordbox is not installed in the test environment, so RekordboxRepository
and RekordboxConnection automatically fall back to their in-memory mock
implementations (MockDatabase) once a dummy db file is supplied via Settings.
"""

from __future__ import annotations

import sqlite3
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from rekordbox_mcp.config import Settings
from rekordbox_mcp.domain.models import OperationMode
from rekordbox_mcp.mcp import server as mcp_server

# Ensure the FastMCP server + all tool modules are created/registered exactly once,
# before importing individual tool functions.
mcp_server.create_mcp_server()

from rekordbox_mcp.mcp.tools_cue import (  # noqa: E402
    add_hot_cue,
    add_loop,
    add_memory_cue,
    generate_cues,
    get_cues,
    update_cue,
)
from rekordbox_mcp.mcp.tools_backup import restore_backup  # noqa: E402
from rekordbox_mcp.mcp.tools_mode import get_mode, get_status, set_mode  # noqa: E402
from rekordbox_mcp.mcp.tools_playlist import (  # noqa: E402
    create_playlist,
    list_playlists,
    process_playlist_cues,
)


@pytest.mark.asyncio
async def test_all_mode_tools_are_registered():
    """Mode tools must be registered on the server returned by get_mcp()."""
    tools = await mcp_server.get_mcp().list_tools()
    names = {tool.name for tool in tools}

    assert {"set_mode", "get_mode", "get_status"} <= names


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
    # Settings.mode is typed as a plain Literal[str]; initialize_services() only
    # overwrites it when `mode != settings.mode`, which is always False for a
    # matching OperationMode/str pair (StrEnum compares equal to its str value).
    # Force it to a real OperationMode instance up front so downstream tools
    # (which call settings.mode.value) work correctly.
    settings.mode = OperationMode.READONLY
    return settings


@pytest.fixture
def readonly_services(mcp_settings: Settings):
    mcp_server.cleanup_services()
    mcp_server.initialize_services(mcp_settings, OperationMode.READONLY)
    # initialize_services() does not itself connect the mock database backing
    # RekordboxRepository; without this the mock tables are never populated.
    mcp_server.get_repository().connect()
    yield
    mcp_server.cleanup_services()


@pytest.fixture
def masterdb_services(mcp_settings: Settings):
    mcp_settings.mode = OperationMode.MASTERDB
    mcp_server.cleanup_services()
    mcp_server.initialize_services(mcp_settings, OperationMode.MASTERDB)
    mcp_server.get_repository().connect()
    yield
    mcp_server.cleanup_services()


@pytest.fixture
def xml_services(mcp_settings: Settings):
    mcp_settings.mode = OperationMode.XML
    mcp_settings.xml_path = str(Path(mcp_settings.backup_dir).parent / "collection.xml")
    mcp_server.cleanup_services()
    mcp_server.initialize_services(mcp_settings, OperationMode.XML)
    mcp_server.get_repository().connect()
    yield
    mcp_server.cleanup_services()


class TestGetCues:
    async def test_get_cues_returns_empty_lists_for_fresh_track(self, readonly_services):
        result = await get_cues(track_id=1)
        assert result["track_id"] == 1
        assert result["cues"] == []
        assert result["hot_cues"] == []
        assert result["memory_cues"] == []


class TestAddHotCue:
    async def test_add_hot_cue_snaps_position_via_beatgrid(self, masterdb_services):
        result = await add_hot_cue(track_id=1, position_ms=1000.0, kind=1, name="Drop")

        assert result["success"] is True
        assert result["cue"]["kind"] == 1
        assert result["cue"]["comment"] == "Drop"
        # Track 1 is 128 BPM with its first beat at 0 ms.
        # Cue persistence uses Rekordbox's integer millisecond fields.
        assert result["cue"]["position_ms"] == pytest.approx(937.0)

    async def test_add_hot_cue_accepts_beat_position(self, masterdb_services):
        result = await add_hot_cue(track_id=1, beat=3, snap="none")

        assert result["success"] is True
        assert result["cue"]["position_ms"] == pytest.approx(937.0)

    async def test_add_hot_cue_accepts_bar_position(self, masterdb_services):
        result = await add_hot_cue(track_id=1, bar=2, snap="none")

        assert result["success"] is True
        assert result["cue"]["position_ms"] == pytest.approx(1875.0)

    async def test_add_hot_cue_accepts_relative_cue_position(self, masterdb_services):
        reference = await add_hot_cue(track_id=1, position_ms=1000.0, kind=1)
        result = await add_hot_cue(
            track_id=1,
            relative_to_cue_id=reference["cue"]["id"],
            relative_offset_beats=1,
            snap="none",
        )

        assert result["success"] is True
        assert result["cue"]["position_ms"] == pytest.approx(1405.0)

    async def test_add_memory_cue_and_loop_use_domain_beatgrid(self, masterdb_services):
        memory_result = await add_memory_cue(track_id=1, position_ms=1000.0, name="Memory")
        loop_result = await add_loop(track_id=1, position_ms=1000.0, loop_end_ms=2500.0)

        assert memory_result["success"] is True
        assert memory_result["cue"]["kind"] == 0
        assert loop_result["success"] is True
        assert loop_result["cue"]["loop_end_ms"] == pytest.approx(2343.0)

    async def test_add_hot_cue_rejected_in_readonly_mode(self, readonly_services):
        with pytest.raises(RuntimeError):
            await add_hot_cue(track_id=1, position_ms=1000.0, kind=1)

    async def test_add_hot_cue_in_xml_mode_writes_collection_xml(self, xml_services, mcp_settings):
        result = await add_hot_cue(track_id=1, position_ms=1000.0, kind=1, name="XML Drop")

        assert result["success"] is True
        root = ET.parse(mcp_settings.xml_path).getroot()
        mark = root.find(".//TRACK[@TrackID='1']/POSITION_MARK")
        assert mark is not None
        assert mark.get("Name") == "XML Drop"
        assert mark.get("Num") == "0"


class TestGenerateCues:
    async def test_generate_cues_creates_cues_for_track(self, masterdb_services):
        result = await generate_cues(track_id=1)

        assert result["success"] is True
        assert result["generated_count"] > 0
        assert len(result["cues"]) == result["generated_count"]
        assert "confidence" in result

    async def test_generate_cues_replace_removes_existing_cues(self, masterdb_services):
        first = await generate_cues(track_id=1)
        replacement = await generate_cues(track_id=1, mode="replace")

        cues = await get_cues(track_id=1)
        assert replacement["success"] is True
        assert len(cues["cues"]) == replacement["generated_count"]
        assert {cue["id"] for cue in cues["cues"]}.isdisjoint(
            {cue["id"] for cue in first["cues"]}
        )

    async def test_generate_cues_rejected_in_readonly_mode(self, readonly_services):
        with pytest.raises(RuntimeError):
            await generate_cues(track_id=1)


class TestProcessPlaylistCues:
    async def test_process_playlist_cues_replace_removes_existing_cues(self, masterdb_services):
        first = await process_playlist_cues(playlist_id="pl1")
        replacement = await process_playlist_cues(playlist_id="pl1", mode="replace")

        assert first["success"] is True
        assert replacement["success"] is True
        for track_id, result in replacement["results"].items():
            cues = await get_cues(track_id=track_id)
            first_cues = first["results"][track_id]["cues"]
            assert len(cues["cues"]) == result["generated"]
            assert {cue["id"] for cue in cues["cues"]}.isdisjoint(
                {cue["id"] for cue in first_cues}
            )


class TestRestoreBackup:
    async def test_restore_backup_rejected_in_xml_mode(self, xml_services):
        result = await restore_backup(backup_id="backup-id")

        assert result["success"] is False
        assert "masterdb" in result["error"]
        assert "xml" in result["error"]


class TestListPlaylists:
    async def test_list_playlists_returns_mock_playlists(self, readonly_services):
        result = await list_playlists()
        names = {p["name"] for p in result["playlists"]}
        assert "My Playlist" in names
        assert result["count"] == len(result["playlists"])


class TestCreatePlaylist:
    async def test_create_playlist_succeeds_in_masterdb_mode(self, masterdb_services):
        result = await create_playlist(name="New Playlist")
        assert result["success"] is True
        assert result["playlist"]["name"] == "New Playlist"
        assert result["playlist"]["attribute"] == 0

    async def test_create_playlist_rejected_in_readonly_mode(self, readonly_services):
        with pytest.raises(RuntimeError):
            await create_playlist(name="Should Fail")


class TestModeTools:
    async def test_get_mode_reflects_current_settings(self, readonly_services):
        result = await get_mode()
        assert result["mode"] == "readonly"

    async def test_set_mode_switches_operation_mode(self, readonly_services):
        result = await set_mode("masterdb")
        assert result["success"] is True
        assert result["mode"] == "masterdb"
        assert result["previous_mode"] == "readonly"

        mode_after = await get_mode()
        assert mode_after["mode"] == "masterdb"

    async def test_set_mode_same_mode_is_noop(self, readonly_services):
        result = await set_mode("readonly")
        assert result["success"] is True
        assert "Already in" in result["message"]

    async def test_set_mode_invalid_mode_rejected(self, readonly_services):
        result = await set_mode("bogus")
        assert result["success"] is False

    async def test_get_status_reports_connection_and_counts(self, readonly_services):
        result = await get_status()
        status = result["status"]
        assert status["mode"] == "readonly"
        assert status["db_connected"] is True
        assert status["track_count"] == 2
        assert status["playlist_count"] == 2


class TestReadonlyRejectsWriteTools:
    async def test_add_hot_cue_readonly_rejected(self, readonly_services):
        with pytest.raises(RuntimeError, match="masterdb or xml"):
            await add_hot_cue(track_id=1, position_ms=500.0)


class TestUpdateCue:
    async def test_update_cue_resolves_track_from_cue_id(self, masterdb_services):
        added = await add_hot_cue(track_id=1, position_ms=1000.0, kind=1, name="Before")
        cue_id = added["cue"]["id"]

        result = await update_cue(cue_id=cue_id, position_ms=2000.0, name="After")

        assert result["success"] is True
        assert result["cue"]["id"] == cue_id
        assert result["cue"]["track_id"] == 1
        assert result["cue"]["comment"] == "After"
        assert result["cue"]["position_ms"] == pytest.approx(1875.0)


class TestReadonlyRejectsOtherWriteTools:
    async def test_create_playlist_readonly_rejected(self, readonly_services):
        with pytest.raises(RuntimeError, match="masterdb or xml"):
            await create_playlist(name="X")

    async def test_generate_cues_readonly_rejected(self, readonly_services):
        with pytest.raises(RuntimeError, match="masterdb or xml"):
            await generate_cues(track_id=1)
