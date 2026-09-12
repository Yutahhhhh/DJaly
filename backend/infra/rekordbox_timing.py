"""Translate rekordbox timestamps to the packaged playback decoder's clock.

Keep cues and imported beat grids on the same timeline. These are the timing
cases used by our pinned Mixxx revision, not a blanket offset for every MP3:
https://github.com/mixxxdj/mixxx/blob/3ebac449e7e5fe2a0186596657696e87ce8b0e56/src/library/rekordbox/rekordboxfeature.cpp
The case definitions are in that revision's lib/mp3guessenc-0.27.4/tags.c.
Only headers are read; importing cues never decodes or analyzes the whole song.
"""
from pathlib import Path
import re
import sys
from mutagen import MutagenError

from api.schemas.performance_metadata import BeatGrid
from infra.rekordbox_grid import RekordboxGridError

VERSION = "rekordbox-decoder-timing-v1"


class RekordboxTimingError(RekordboxGridError):
    pass


def _crc16(data: bytes) -> int:
    """LAME info-tag CRC: reflected 0x8005 (0xa001), initial value zero."""
    value = 0
    for byte in data:
        value ^= byte
        for _ in range(8):
            value = (value >> 1) ^ (0xa001 if value & 1 else 0)
    return value


def mp3_timing_case(filepath: str) -> str:
    from mutagen.mp3 import MPEGInfo

    try:
        with open(filepath, "rb") as source:
            # Mutagen skips ID3 tags and bounds its MPEG sync search to 1 MiB.
            info = MPEGInfo(source)
            if info.layer != 3:
                raise ValueError("not MPEG layer III")
            source.seek(info.frame_offset)
            frame = source.read(2048)
        if len(frame) < 40:
            raise ValueError("truncated MPEG header")
        # Xing follows the MPEG header and side information. Its offset does
        # not include the optional MPEG CRC (the format's established layout).
        xing = 4 + ((17 if info.channels == 1 else 32) if info.version == 1
                    else (9 if info.channels == 1 else 17))
        if frame[36:40] == b"VBRI":
            return "D"
        if frame[xing:xing + 4] not in (b"Xing", b"Info"):
            return "A"
        flags = int.from_bytes(frame[xing + 4:xing + 8], "big")
        position = xing + 8 + (4 if flags & 1 else 0) + (4 if flags & 2 else 0) + (100 if flags & 4 else 0)
        if frame[position:position + 4] == b"GOGO":
            return "B"
        position += 4 if flags & 8 else 0
        signature = frame[position:position + 9]
        if len(signature) < 9:
            raise ValueError("truncated encoder tag")
        if signature.lower().startswith(b"lavc"):
            return "B"
        recognized = signature.startswith(b"LAME") or re.match(rb"L\d\.\d\d", signature)
        if not recognized or re.match(rb"LAME3\.[0-8]\d\D", signature):
            return "B"
        end = position + 36
        if end > len(frame):
            raise ValueError("truncated LAME tag")
        return "D" if _crc16(frame[:end - 2]) == int.from_bytes(frame[end - 2:end], "big") else "C"
    except (OSError, ValueError, MutagenError) as exc:
        raise RekordboxTimingError("音源の時刻情報を読めません。音源の場所とMP3形式を確認してください") from exc


def timing_offset_ms(filepath: str, *, platform: str | None = None) -> float:
    platform = sys.platform if platform is None else platform
    extension = Path(filepath).suffix.lower()
    # The shipped macOS build prefers CoreAudio. Windows builds enable MAD;
    # its MP3 provider precedes the libsndfile fallback. Other codecs are not
    # shifted using the MP3 table.
    if platform not in {"darwin", "win32"}:
        return 0.0
    if extension == ".mp3":
        case = mp3_timing_case(filepath)
        return float({"A": 12, "B": 13, "C": 26, "D": 50}[case] if platform == "darwin"
                     else {"A": 26, "B": 0, "C": 0, "D": 26}[case])
    if platform == "darwin" and extension == ".m4a":
        from mutagen.mp4 import MP4
        try:
            info = MP4(filepath).info
            # ALAC shares the M4A container but has no AAC encoder delay.
            return 48.0 if info.codec.startswith("mp4a") else 0.0
        except (OSError, ValueError, AttributeError, MutagenError) as exc:
            raise RekordboxTimingError("M4A音源のコーデック情報を読めません") from exc
    return 0.0


def adjust_grid(grid: BeatGrid, offset_ms: float) -> BeatGrid:
    if not offset_ms:
        return grid
    values = grid.model_dump()
    if grid.beat_times_ms:
        kept = [(i, t - offset_ms) for i, t in enumerate(grid.beat_times_ms) if t >= offset_ms]
        if len(kept) < 2:
            raise RekordboxTimingError("時刻補正後のビートが不足しています")
        values["beat_times_ms"] = [t for _, t in kept]
        values["first_beat_ms"] = kept[0][1]
        if grid.beat_numbers:
            values["beat_numbers"] = [grid.beat_numbers[i] for i, _ in kept]
    else:
        first = grid.first_beat_ms - offset_ms
        period = 60_000 / grid.bpm
        while first < 0:
            first += period
        values["first_beat_ms"] = first
    return BeatGrid.model_validate(values)
