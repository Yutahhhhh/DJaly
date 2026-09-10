"""Read-only rekordbox master.db lookup and bounded, exact PQTZ decoding.

Format: https://djl-analysis.deepsymmetry.org/rekordbox-export-analysis/anlz.html
Never instantiate Rekordbox6Database: its higher-level APIs can modify the library.
"""
from __future__ import annotations

import os
from pathlib import Path
import statistics
import struct
import sys

from api.schemas.performance_metadata import BeatGrid

MAX_ANLZ_BYTES = 32 * 1024 * 1024


class RekordboxGridError(ValueError):
    pass


def master_db_path() -> Path | None:
    explicit = os.environ.get("PLUMDECK_REKORDBOX_DB")
    if explicit:
        return Path(explicit).expanduser()
    if sys.platform == "darwin":
        return Path.home() / "Library/Pioneer/rekordbox/master.db"
    if sys.platform == "win32" and os.environ.get("APPDATA"):
        return Path(os.environ["APPDATA"]) / "Pioneer/rekordbox/master.db"
    return None


def connect_readonly(path: Path):
    try:
        from pyrekordbox.db6.database import BLOB, deobfuscate
        from sqlcipher3 import dbapi2
    except ImportError as exc:
        raise RekordboxGridError("rekordbox reading requires bundled pyrekordbox and SQLCipher") from exc
    connection = dbapi2.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=2)
    try:
        connection.execute("PRAGMA key='" + deobfuscate(BLOB).replace("'", "''") + "'")
        connection.execute("PRAGMA query_only=ON")
        connection.execute("BEGIN")
        return connection
    except Exception:
        connection.close()
        raise


def find_analysis(filepath: str, database: Path | None = None) -> tuple[Path, str] | None:
    database = database or master_db_path()
    if database is None or not database.is_file():
        return None
    try:
        connection = connect_readonly(database)
        try:
            # Exact path identity, never title/artist guessing; parameterized and WAL-aware.
            rows = connection.execute(
                "SELECT ID, AnalysisDataPath FROM djmdContent "
                "WHERE FolderPath = ? AND rb_local_deleted = 0", (filepath,),
            ).fetchall()
        finally:
            connection.close()
        if not rows:
            return None
        paths = {str(row[1]) for row in rows if row[1]}
        if len(paths) > 1:
            raise RekordboxGridError("Multiple rekordbox grids match this audio path")
        if not paths:
            return None
        raw = next(iter(paths)).replace("\\", "/")
        analysis = Path(raw)
        # Rekordbox stores /share/... paths relative to the library directory.
        if not analysis.is_file():
            candidates = [database.parent / "share" / raw.lstrip("/"),
                          database.parent / raw.lstrip("/")]
            analysis = next((p for p in candidates if p.is_file()), candidates[0])
        if not analysis.is_file():
            return None
        return analysis, str(rows[0][0])
    except RekordboxGridError:
        raise
    except Exception as exc:
        raise RekordboxGridError("Could not read the local rekordbox library") from exc


def parse_pqtz(data: bytes) -> BeatGrid | None:
    if len(data) < 12 or len(data) > MAX_ANLZ_BYTES or data[:4] != b"PMAI":
        raise RekordboxGridError("Invalid ANLZ header")
    header_size, file_size = struct.unpack_from(">II", data, 4)
    if not 12 <= header_size <= file_size == len(data):
        raise RekordboxGridError("Invalid ANLZ length")
    offset = header_size
    while offset < file_size:
        if offset + 12 > file_size:
            raise RekordboxGridError("Truncated ANLZ section")
        kind, header, size = struct.unpack_from(">4sII", data, offset)
        if not 12 <= header <= size or offset + size > file_size:
            raise RekordboxGridError("Invalid ANLZ section length")
        if kind == b"PQTZ":
            if header != 24:
                raise RekordboxGridError("Invalid PQTZ header")
            count = struct.unpack_from(">I", data, offset + 20)[0]
            if count > 100000 or 24 + count * 8 != size:
                raise RekordboxGridError("Invalid PQTZ beat count")
            if count < 2:
                return None
            entries = list(struct.iter_unpack(">HHI", data[offset + 24:offset + size]))
            numbers, tempos, times = map(list, zip(*entries))
            try:
                return BeatGrid(bpm=statistics.median(tempos) / 100,
                                first_beat_ms=times[0], beats_per_bar=max(numbers),
                                beat_times_ms=times, beat_numbers=numbers,
                                source="rekordbox", confidence=None)
            except ValueError as exc:
                raise RekordboxGridError("Invalid PQTZ beat values") from exc
        offset += size
    return None


def read_grid(path: Path) -> BeatGrid | None:
    with path.open("rb") as source:
        return parse_pqtz(source.read(MAX_ANLZ_BYTES + 1))
