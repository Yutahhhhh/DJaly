"""Tests for graceful behavior when no Rekordbox database exists.

When ``get_db_path()`` returns ``None`` (no master.db found), the server must
still start: ``initialize_services()`` must not raise, ``get_status`` must
report ``db_connected=False``, and database-dependent tools must return a
graceful ``{"success": False, "error": ...}`` response instead of raising an
MCP protocol error.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from rekordbox_mcp.config import Settings
from rekordbox_mcp.db.connection import RekordboxConnection
from rekordbox_mcp.domain.models import OperationMode
from rekordbox_mcp.mcp import server as mcp_server

# Ensure the FastMCP server + all tool modules are created/registered exactly once,
# before importing individual tool functions.
mcp_server.create_mcp_server()

from rekordbox_mcp.mcp.tools_cue import add_hot_cue, get_cues  # noqa: E402
from rekordbox_mcp.mcp.tools_mode import get_status  # noqa: E402
from rekordbox_mcp.mcp.tools_playlist import list_playlists  # noqa: E402


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
    """Services initialized in an environment with no Rekordbox database.

    ``get_db_path()`` is forced to return ``None`` so the test is deterministic
    even on machines where Rekordbox is installed (auto-detection would
    otherwise find a real master.db).
    """
    monkeypatch.setattr(RekordboxConnection, "get_db_path", lambda self: None)
    mcp_server.cleanup_services()
    mcp_server.initialize_services(no_db_settings, OperationMode.READONLY)
    yield
    mcp_server.cleanup_services()


class TestInitializeWithoutDb:
    async def test_initialize_services_does_not_raise(self, unavailable_services):
        """Server startup must succeed even when no database exists."""
        conn = mcp_server.get_connection()
        assert conn.is_connected is False
        assert conn.db_unavailable_reason is not None
        assert "not found" in conn.db_unavailable_reason.lower()

    async def test_repository_reports_unavailable(self, unavailable_services):
        """Repository methods raise a clear error instead of serving mock data."""
        repo = mcp_server.get_repository()
        with pytest.raises(RuntimeError, match="not available"):
            repo.get_playlists()
        with pytest.raises(RuntimeError, match="not available"):
            repo.get_tracks()


class TestGetStatusWithoutDb:
    async def test_get_status_reports_db_unavailable(self, unavailable_services):
        result = await get_status()

        assert result["success"] is True
        status = result["status"]
        assert status["db_connected"] is False
        assert status["db_unavailable_reason"] is not None
        assert status["db_path"] is None
        assert status["track_count"] == 0
        assert status["playlist_count"] == 0


class TestToolsWithoutDb:
    async def test_list_playlists_returns_graceful_error(self, unavailable_services):
        result = await list_playlists()

        assert result["success"] is False
        assert "not available" in result["error"].lower()

    async def test_get_cues_returns_graceful_error(self, unavailable_services):
        result = await get_cues(track_id=1)

        assert result["success"] is False
        assert "not available" in result["error"].lower()

    async def test_write_tool_returns_graceful_error(self, unavailable_services):
        result = await add_hot_cue(track_id=1, position_ms=1000.0, kind=1)

        assert result["success"] is False
        assert "not available" in result["error"].lower()