"""Read hot cues from rekordbox's encrypted library without modifying it."""
from __future__ import annotations

from pathlib import Path
from typing import Any
from dataclasses import dataclass, field
import math
import sys
from infra.rekordbox_library import same_path

from api.schemas.performance_metadata import CuePoint
from infra.rekordbox_grid import connect_readonly, master_db_path


# rekordbox reserves Kind=4 and maps pads D-H to 5-9.
HOT_CUE_SLOTS = {1: 0, 2: 1, 3: 2, 5: 3, 6: 4, 7: 5, 8: 6, 9: 7}
PATH_BATCH_SIZE = 400


class RekordboxCueError(ValueError):
    pass


class RekordboxCueTrackNotFoundError(RekordboxCueError):
    pass


@dataclass
class RekordboxCueBulkResult:
    cues_by_path: dict[str, list[CuePoint]] = field(default_factory=dict)
    errors_by_path: dict[str, str] = field(default_factory=dict)


def _content_id(connection: Any, filepath: str) -> str | None:
    if sys.platform == "win32":
        candidates = connection.execute(
            "SELECT ID, FolderPath FROM djmdContent "
            "WHERE replace(FolderPath, char(92), '/') COLLATE NOCASE = ? AND rb_local_deleted = 0",
            (filepath.replace("\\", "/"),),
        ).fetchall()
        rows = [row[:1] for row in candidates if same_path(filepath, str(row[1]))]
    else:
        rows = connection.execute(
            "SELECT ID FROM djmdContent "
            "WHERE FolderPath = ? AND rb_local_deleted = 0",
            (filepath,),
        ).fetchall()
    ids = {str(row[0]) for row in rows if row[0] is not None}
    if len(ids) > 1:
        raise RekordboxCueError("Multiple rekordbox tracks match this audio path")
    return next(iter(ids), None)


def read_hot_cues(filepath: str, database: Path | None = None) -> list[CuePoint]:
    """Return pads A-H for an exact audio path, ordered by pad slot.

    An exact rekordbox track with no hot cues returns an empty list. A missing
    database or unmatched path is reported separately so an import cannot
    silently clear plumdeck cues for the wrong source.
    """
    database = database or master_db_path()
    if database is None or not database.is_file():
        raise RekordboxCueTrackNotFoundError("The local rekordbox library is unavailable")
    try:
        connection = connect_readonly(database)
        try:
            content_id = _content_id(connection, filepath)
            if content_id is None:
                raise RekordboxCueTrackNotFoundError(
                    "No rekordbox track matches this audio file path"
                )
            placeholders = ",".join("?" for _ in HOT_CUE_SLOTS)
            rows = connection.execute(
                "SELECT Kind, InMsec, Comment FROM djmdCue "
                f"WHERE ContentID = ? AND rb_local_deleted = 0 AND Kind IN ({placeholders}) "
                "ORDER BY Kind",
                (content_id, *HOT_CUE_SLOTS),
            ).fetchall()
        finally:
            connection.close()
    except RekordboxCueError:
        raise
    except Exception as exc:
        raise RekordboxCueError("Could not read cues from the local rekordbox library") from exc

    return _cue_points(rows)


def _cue_points(rows: list[tuple[Any, Any, Any]]) -> list[CuePoint]:
    cues: list[CuePoint] = []
    seen: set[int] = set()
    for kind, position_ms, comment in rows:
        if kind is None:
            continue
        slot = HOT_CUE_SLOTS.get(kind)
        if slot is None:
            continue
        if slot in seen:
            raise RekordboxCueError(f"Multiple rekordbox cues use hot cue slot {slot + 1}")
        if (not isinstance(position_ms, (int, float))
                or not math.isfinite(position_ms) or position_ms < 0):
            raise RekordboxCueError(f"Invalid rekordbox hot cue position in slot {slot + 1}")
        seen.add(slot)
        label = str(comment or "").strip() or chr(ord("A") + slot)
        try:
            cues.append(CuePoint(
                slot=slot,
                position_ms=position_ms,
                label=label[:100],
                color=None,
            ))
        except ValueError as exc:
            raise RekordboxCueError(
                f"Invalid rekordbox hot cue in slot {slot + 1}"
            ) from exc
    return cues


def read_hot_cues_bulk(
    filepaths: list[str],
    database: Path | None = None,
) -> RekordboxCueBulkResult:
    """Read all exact-path matches using one connection and bounded queries."""
    result = RekordboxCueBulkResult()
    unique_paths = list(dict.fromkeys(filepaths))
    if not unique_paths:
        return result
    database = database or master_db_path()
    if database is None or not database.is_file():
        raise RekordboxCueTrackNotFoundError("The local rekordbox library is unavailable")

    try:
        connection = connect_readonly(database)
        try:
            for offset in range(0, len(unique_paths), PATH_BATCH_SIZE):
                batch = unique_paths[offset:offset + PATH_BATCH_SIZE]
                placeholders = ",".join("?" for _ in batch)
                column = "content.FolderPath"
                parameters = batch
                if sys.platform == "win32":
                    column = "replace(content.FolderPath, char(92), '/') COLLATE NOCASE"
                    parameters = [path.replace("\\", "/") for path in batch]
                rows = connection.execute(
                    "SELECT content.FolderPath, content.ID, cue.Kind, cue.InMsec, cue.Comment "
                    "FROM djmdContent AS content "
                    "LEFT JOIN djmdCue AS cue ON cue.ContentID = content.ID "
                    "AND cue.rb_local_deleted = 0 "
                    f"AND cue.Kind IN ({','.join('?' for _ in HOT_CUE_SLOTS)}) "
                    "WHERE content.rb_local_deleted = 0 "
                    f"AND {column} IN ({placeholders}) "
                    "ORDER BY content.FolderPath, cue.Kind",
                    (*HOT_CUE_SLOTS, *parameters),
                ).fetchall()
                grouped: dict[str, dict[str, list[tuple[Any, Any, Any]]]] = {}
                for filepath, content_id, kind, position_ms, comment in rows:
                    aliases = [str(filepath)]
                    if sys.platform == "win32":
                        aliases = [requested for requested in batch if same_path(requested, str(filepath))]
                    for alias in aliases:
                        grouped.setdefault(alias, {}).setdefault(str(content_id), []).append(
                            (kind, position_ms, comment)
                        )
                for filepath, contents in grouped.items():
                    if len(contents) != 1:
                        result.errors_by_path[filepath] = (
                            "Multiple rekordbox tracks match this audio path"
                        )
                        continue
                    try:
                        result.cues_by_path[filepath] = _cue_points(next(iter(contents.values())))
                    except RekordboxCueError as exc:
                        result.errors_by_path[filepath] = str(exc)
        finally:
            connection.close()
    except RekordboxCueError:
        raise
    except Exception as exc:
        raise RekordboxCueError("Could not read cues from the local rekordbox library") from exc
    return result
