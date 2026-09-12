import sqlite3
import struct

import pytest

from api.schemas.performance_metadata import BeatGrid
from infra import rekordbox_cues, rekordbox_timing as timing


def mp3_header_fixture(case, mono=False, version=1):
    # Valid MPEG layer III frame chain. The encoded sound is irrelevant to a
    # header-only import; no whole-track decoder is required by these tests.
    header = bytes([0xff, 0xfb if version == 1 else 0xf3, 0x90, 0xc4 if mono else 0x04])
    size = 417 if version == 1 else 261
    frame = bytearray(header + bytes(size - 4))
    xing = 4 + ((17 if mono else 32) if version == 1 else (9 if mono else 17))
    if case == "VBRI":
        frame[36:62] = struct.pack(">4sHHHIIHHHH", b"VBRI", 1, 0, 0, size * 5, 5, 0, 1, 2, 1)
    elif case != "A":
        frame[xing:xing + 16] = b"Xing" + struct.pack(">III", 3, 4, size * 5)
        position = xing + 16
        frame[position:position + 9] = b"Lavc60.31" if case == "B" else b"LAME3.100"
        crc = timing._crc16(frame[:position + 34])
        frame[position + 34:position + 36] = (crc ^ (case == "C")).to_bytes(2, "big")
    return bytes(frame) + (header + bytes(size - 4)) * 4


@pytest.mark.parametrize("case,mac,windows", [("A",12,26),("B",13,0),("C",26,0),("D",50,26),("VBRI",50,26)])
@pytest.mark.parametrize("mono,version", [(False,1),(True,1),(False,2),(True,2)])
def test_encoder_cases_match_packaged_mixxx_policy(tmp_path, case, mac, windows, mono, version):
    path = tmp_path / "音源・東京.MP3"
    path.write_bytes(mp3_header_fixture(case, mono, version))
    assert timing.mp3_timing_case(str(path)) == ("D" if case == "VBRI" else case)
    assert timing.timing_offset_ms(str(path), platform="darwin") == mac
    assert timing.timing_offset_ms(str(path), platform="win32") == windows
    assert timing.timing_offset_ms(str(path), platform="linux") == 0


def test_crc_and_large_id3_do_not_turn_valid_lame_into_unverified(tmp_path):
    assert timing._crc16(b"123456789") == 0xbb3d  # standard CRC-16/ARC check value
    size = 2 * 1024 * 1024
    synchsafe = bytes((size >> shift) & 0x7f for shift in (21,14,7,0))
    path = tmp_path / "large-cover.mp3"
    path.write_bytes(b"ID3\x04\x00\x00" + synchsafe + bytes(size) + mp3_header_fixture("D"))
    assert timing.mp3_timing_case(str(path)) == "D"


def test_unreadable_audio_fails_explicitly_and_other_formats_are_not_shifted(tmp_path):
    bad = tmp_path / "invalid.mp3"
    bad.write_bytes(b"not audio")
    for path in (bad, tmp_path / "missing.mp3"):
        with pytest.raises(timing.RekordboxTimingError):
            timing.timing_offset_ms(str(path), platform="darwin")
    for suffix in ("wav","flac","aiff","ogg"):
        assert timing.timing_offset_ms(str(tmp_path / f"unopened.{suffix}"), platform="darwin") == 0


def test_single_and_bulk_cues_share_one_adjustment_and_reimport_is_idempotent(tmp_path, monkeypatch):
    audio = tmp_path / "東京.mp3"
    audio.write_bytes(mp3_header_fixture("D"))
    database = tmp_path / "master.db"
    with sqlite3.connect(database) as con:
        con.execute("CREATE TABLE djmdContent (ID TEXT, FolderPath TEXT, rb_local_deleted INT DEFAULT 0)")
        con.execute("CREATE TABLE djmdCue (ContentID TEXT, Kind INT, InMsec INT, Comment TEXT, rb_local_deleted INT DEFAULT 0)")
        con.execute("INSERT INTO djmdContent (ID,FolderPath) VALUES ('1', ?)", (str(audio),))
        con.executemany("INSERT INTO djmdCue (ContentID,Kind,InMsec,Comment) VALUES ('1', ?, ?, ?)", [(1,30,"start"),(2,1250,"drop"),(4,3000,"not a hot cue")])
    monkeypatch.setattr(rekordbox_cues, "connect_readonly", sqlite3.connect)
    monkeypatch.setattr(rekordbox_cues, "timing_offset_ms", lambda path: timing.timing_offset_ms(path, platform="darwin"))
    first = rekordbox_cues.read_hot_cues(str(audio), database)
    assert [(c.slot,c.position_ms,c.label) for c in first] == [(0,0,"start"),(1,1200,"drop")]
    assert rekordbox_cues.read_hot_cues(str(audio), database) == first
    bulk = rekordbox_cues.read_hot_cues_bulk([str(audio)], database)
    assert bulk.cues_by_path[str(audio)] == first
    with sqlite3.connect(database) as con:
        assert con.execute("SELECT InMsec FROM djmdCue WHERE Kind=2").fetchone()[0] == 1250
    audio.unlink()
    bulk = rekordbox_cues.read_hot_cues_bulk([str(audio)], database)
    assert str(audio) in bulk.errors_by_path


def test_grid_uses_same_clock_and_keeps_transition_intervals_and_bar_phase():
    original = BeatGrid(bpm=120, first_beat_ms=30, beat_times_ms=[30,530,1030,1630,2230],
                        beat_numbers=[4,1,2,3,4], source="rekordbox")
    shifted = timing.adjust_grid(original, 50)
    assert shifted.beat_times_ms == [480,980,1580,2180]
    assert shifted.beat_numbers == [1,2,3,4]
    assert original.beat_times_ms[0] == 30


@pytest.mark.parametrize("codec,expected", [("mp4a.40.2",48),("alac",0)])
def test_mac_m4a_compensates_aac_but_not_alac(monkeypatch, codec, expected):
    from types import SimpleNamespace
    import mutagen.mp4
    monkeypatch.setattr(mutagen.mp4, "MP4", lambda _: SimpleNamespace(info=SimpleNamespace(codec=codec)))
    assert timing.timing_offset_ms("track.m4a", platform="darwin") == expected
