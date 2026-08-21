"""Shared pytest fixtures for rekordbox-mcp tests."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from rekordbox_mcp.config import Settings
from rekordbox_mcp.domain.beatgrid import BeatGrid
from rekordbox_mcp.domain.models import (
    CuePoint,
    Phrase,
    Track,
    WaveformPoint,
)


@pytest.fixture
def test_settings(tmp_path: Path) -> Settings:
    """Settings instance pointed at a temporary backup directory."""
    return Settings(
        backup_dir=str(tmp_path / "backups"),
        backup_max_days=14,
        backup_max_generations=20,
        backup_max_size_gb=2.0,
        backup_compression_level=3,
        mode="readonly",
    )


@pytest.fixture
def sample_beatgrid() -> BeatGrid:
    """A simple 128 BPM beat grid starting at 100ms."""
    return BeatGrid(first_beat_ms=100.0, bpm=128.0)


@pytest.fixture
def sample_cue() -> CuePoint:
    """A sample hot cue point."""
    return CuePoint(
        track_id=1,
        kind=1,
        position_ms=1000.0,
        comment="First Beat",
    )


@pytest.fixture
def sample_phrases(sample_beatgrid: BeatGrid) -> list[Phrase]:
    """A simple phrase structure: Intro -> Up -> Chorus -> Down -> Outro."""
    bg = sample_beatgrid
    structure = [
        ("Intro", 1, 16),
        ("Up", 16, 48),
        ("Chorus", 48, 80),
        ("Down", 80, 96),
        ("Outro", 96, 112),
    ]
    phrases = []
    for label, beat_start, beat_end in structure:
        pos_ms = bg.beat_to_ms(beat_start)
        end_ms = bg.beat_to_ms(beat_end)
        phrases.append(
            Phrase(
                beat_start=beat_start,
                beat_end=beat_end,
                kind=1,
                label=label,
                position_ms=pos_ms,
                duration_ms=end_ms - pos_ms,
                mood=1,
            )
        )
    return phrases


@pytest.fixture
def sample_waveform() -> list[WaveformPoint]:
    """A simple waveform with 400 points of varying energy."""
    points = []
    for i in range(400):
        # Create a dip in the middle third to simulate a breakdown/recovery
        if 130 <= i < 200:
            height = 0.2
        else:
            height = 0.8
        points.append(WaveformPoint(height=height, red=4, green=4, blue=4))
    return points


@pytest.fixture
def sample_track(sample_beatgrid: BeatGrid, sample_phrases: list[Phrase]) -> Track:
    """A sample track with beat grid and phrases, no existing cues."""
    duration_ms = sample_beatgrid.beat_to_ms(112) + 4000
    return Track(
        id=1,
        title="Test Track",
        artist="Test Artist",
        bpm=sample_beatgrid.bpm,
        duration_ms=duration_ms,
        analysis_path="/mock/analysis/1.anlz",
        key="5A",
        genre="House",
        cues=[],
        phrases=sample_phrases,
        beat_grid=sample_beatgrid.to_model(),
        waveform=None,
        vocal_track=None,
    )


class FakeDatabaseAccessor:
    """In-memory DatabaseAccessor for BackupManager tests, backed by a real sqlite file."""

    def __init__(self, db_path: Path):
        self._db_path = db_path
        self._version = "1.0.0-test"
        self._init_db()

    def _init_db(self) -> None:
        conn = sqlite3.connect(self._db_path)
        conn.execute(
            "CREATE TABLE djmdCue (ID TEXT PRIMARY KEY, ContentID INTEGER, Kind INTEGER, InMsec INTEGER)"
        )
        conn.execute(
            "CREATE TABLE djmdPlaylist (ID TEXT PRIMARY KEY, Name TEXT, ParentID TEXT)"
        )
        conn.execute(
            "CREATE TABLE djmdContent (ID INTEGER PRIMARY KEY, Title TEXT, Artist TEXT)"
        )
        conn.execute("INSERT INTO djmdCue VALUES ('cue-1', 1, 1, 1000)")
        conn.execute("INSERT INTO djmdCue VALUES ('cue-2', 1, 0, 2000)")
        conn.execute("INSERT INTO djmdPlaylist VALUES ('pl-1', 'My Playlist', 'root')")
        conn.execute("INSERT INTO djmdContent VALUES (1, 'Test Track', 'Test Artist')")
        conn.commit()
        conn.close()

    def get_connection(self) -> sqlite3.Connection:
        return sqlite3.connect(self._db_path)

    def get_db_path(self) -> Path:
        return self._db_path

    def get_db_version(self) -> str:
        return self._version


@pytest.fixture
def mock_db_accessor(tmp_path: Path) -> FakeDatabaseAccessor:
    """A mock DatabaseAccessor backed by a real temp sqlite file."""
    db_path = tmp_path / "master.db"
    return FakeDatabaseAccessor(db_path)
