"""Tests for the Web API cue endpoints."""

from __future__ import annotations

from unittest.mock import Mock

import pytest

from rekordbox_mcp.domain.models import CuePoint, OperationMode
from rekordbox_mcp.webapi.routers import cues as cues_router


@pytest.mark.asyncio
async def test_add_hot_cue_endpoint_converts_model_beatgrid(monkeypatch, sample_track):
    """The endpoint passes a domain BeatGrid to CueManager and persists the cue."""
    saved = []
    repo = Mock()
    repo.get_track.return_value = sample_track
    repo.get_cues.return_value = []
    repo.add_cue.side_effect = lambda _track_id, cue: (saved.append(cue), cue)[1]

    monkeypatch.setattr(cues_router, "get_repository", lambda: repo)
    monkeypatch.setattr(cues_router, "check_write_mode", lambda: OperationMode.MASTERDB)

    result = await cues_router.add_hot_cue(cues_router.AddHotCueRequest(
        track_id=sample_track.id, position_ms=110.0, name="Intro"
    ))

    assert result["success"] is True
    assert result["cue"]["comment"] == "Intro"
    assert result["cue"]["position_ms"] == pytest.approx(100.0)
    assert len(saved) == 1


@pytest.mark.asyncio
async def test_snap_endpoint_uses_domain_beatgrid(monkeypatch, sample_track):
    existing = CuePoint(id="cue-1", track_id=sample_track.id, kind=1, position_ms=110.0)
    repo = Mock()
    repo.get_track.return_value = sample_track
    repo.get_cues.return_value = [existing]
    repo.update_cue.side_effect = lambda _cue_id, data: CuePoint(**data)

    monkeypatch.setattr(cues_router, "get_repository", lambda: repo)
    monkeypatch.setattr(cues_router, "check_write_mode", lambda: OperationMode.MASTERDB)

    result = await cues_router.snap_to_beatgrid(sample_track.id, "cue-1")

    assert result["success"] is True
    assert result["cue"]["position_ms"] == pytest.approx(100.0)
    repo.update_cue.assert_called_once()
