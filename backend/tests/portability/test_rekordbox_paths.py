"""Windows file aliases must resolve to the same real file, never by title."""
from pathlib import Path
import sqlite3
import sys

import pytest

from infra import rekordbox_library, rekordbox_grid, rekordbox_cues


@pytest.mark.skipif(sys.platform != "win32", reason="Exercises the Windows filesystem")
def test_windows_slashes_case_and_unicode_preserve_track_identity(tmp_path, monkeypatch):
    audio = tmp_path / "音楽 Track.wav"
    audio.write_bytes(b"fixture")
    analysis = tmp_path / "ANLZ0000.DAT"
    analysis.write_bytes(b"fixture")
    database = tmp_path / "master.db"
    stored = str(audio).replace("\\", "/").lower()
    connection = sqlite3.connect(database)
    connection.executescript("""
        CREATE TABLE djmdContent (ID TEXT, FolderPath TEXT, Title TEXT, ArtistID TEXT,
            BPM INTEGER, AnalysisDataPath TEXT, rb_local_deleted INTEGER);
        CREATE TABLE djmdArtist (ID TEXT, Name TEXT);
        CREATE TABLE djmdCue (ContentID TEXT, Kind INTEGER, InMsec INTEGER, Comment TEXT, rb_local_deleted INTEGER);
    """)
    connection.execute("INSERT INTO djmdContent VALUES (?, ?, ?, ?, ?, ?, 0)",
        ("track-id", stored, "Track", "artist-id", 12000, str(analysis)))
    connection.execute("INSERT INTO djmdArtist VALUES ('artist-id', 'Artist')")
    connection.execute("INSERT INTO djmdCue VALUES ('track-id', 1, 100, 'Intro', 0)")
    connection.commit()
    connection.close()
    for module, attribute in [(rekordbox_library, "_connect"), (rekordbox_grid, "connect_readonly"), (rekordbox_cues, "connect_readonly")]:
        monkeypatch.setattr(module, attribute, lambda path: sqlite3.connect(path))
    monkeypatch.setattr(rekordbox_library, "_database", lambda: database)
    entries = rekordbox_library.lookup_by_paths([str(audio)])
    assert entries[stored].content_id == "track-id"
    assert rekordbox_library.is_registered_path(str(audio), frozenset([stored]))
    assert rekordbox_grid.find_analysis(str(audio), database) == (analysis, "track-id")
    assert rekordbox_cues.read_hot_cues(str(audio), database)[0].position_ms == 100
    assert rekordbox_cues.read_hot_cues_bulk([str(audio)], database).cues_by_path[str(audio)][0].position_ms == 100
    other = tmp_path / "different.wav"
    other.write_bytes(b"fixture")
    assert not rekordbox_library.same_path(str(audio), str(other))
    assert not rekordbox_library.is_registered_path(str(other), frozenset([stored]))
