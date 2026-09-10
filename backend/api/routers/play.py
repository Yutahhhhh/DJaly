import os
import shutil
import subprocess
import sys
import tempfile
import threading
import unicodedata
from datetime import datetime
from functools import lru_cache, wraps

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy import text
from sqlmodel import Session

from api.schemas.play import (
    HistoryUpsert, LocalPlaylistCreate, LocalPlaylistRename, LocalPlaylistTrackAdd,
    MirrorImport, MirrorPlaylistCopy, PlaySessionCreate, RecordingUpsert,
    RecordingName,
)
from app.services.setlist_app_service import SetlistAppService
from domain.models.setlist import Setlist
from infra.database.connection import get_session

router = APIRouter(prefix="/api/play", tags=["play"])

_RECORDING_MEDIA_TYPES = {
    ".wav": "audio/wav", ".wave": "audio/wav",
    ".aif": "audio/aiff", ".aiff": "audio/aiff",
    ".flac": "audio/flac", ".mp3": "audio/mpeg",
    ".ogg": "audio/ogg", ".oga": "audio/ogg",
}
_EXPORT_FORMATS = {
    "wav": {"extension": ".wav", "label": "WAV（可逆・最大サイズ）", "encoder": "pcm_s16le"},
    "flac": {"extension": ".flac", "label": "FLAC（可逆・圧縮）", "encoder": "flac"},
    "mp3": {"extension": ".mp3", "label": "MP3（非可逆）", "encoder": "libmp3lame"},
}
_recording_mutation_lock = threading.RLock()


def _serialize_recording_mutation(function):
    @wraps(function)
    def serialized(*args, **kwargs):
        with _recording_mutation_lock:
            return function(*args, **kwargs)
    return serialized


def _rows(result):
    return [dict(row._mapping) for row in result]


def _normalized_filepath(filepath: str) -> str:
    return unicodedata.normalize("NFC", os.path.normcase(os.path.realpath(os.path.expanduser(filepath))))


@router.get("/playlists")
def local_playlists(
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    session: Session = Depends(get_session),
):
    return SetlistAppService(session).get_setlists_page(limit, offset)


@router.post("/playlists")
def create_local_playlist(payload: LocalPlaylistCreate, session: Session = Depends(get_session)):
    name = payload.name.strip()
    if not name:
        raise HTTPException(422, "Playlist name cannot be blank")
    item = SetlistAppService(session).create_setlist(name)
    result = item.model_dump(mode="json")
    result.update({"source": "plumdeck", "editable": True, "track_count": 0})
    return result


@router.patch("/playlists/{playlist_id}")
def rename_local_playlist(
    playlist_id: int, payload: LocalPlaylistRename, session: Session = Depends(get_session),
):
    name = payload.name.strip()
    if not name:
        raise HTTPException(422, "Playlist name cannot be blank")
    item = SetlistAppService(session).update_setlist(playlist_id, {"name": name})
    if not item:
        raise HTTPException(404, "Local playlist not found")
    result = item.model_dump(mode="json")
    result.update({"source": "plumdeck", "editable": True})
    return result


@router.delete("/playlists/{playlist_id}")
def delete_local_playlist(playlist_id: int, session: Session = Depends(get_session)):
    if not SetlistAppService(session).delete_setlist(playlist_id):
        raise HTTPException(404, "Local playlist not found")
    return {"ok": True}


@router.get("/playlists/{playlist_id}/tracks")
def local_playlist_tracks(
    playlist_id: int,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    session: Session = Depends(get_session),
):
    page = SetlistAppService(session).get_setlist_tracks_page(playlist_id, limit, offset)
    if page is None:
        raise HTTPException(404, "Local playlist not found")
    return page


@router.post("/playlists/{playlist_id}/tracks")
def add_local_playlist_track(
    playlist_id: int, payload: LocalPlaylistTrackAdd, session: Session = Depends(get_session),
):
    try:
        entry_id = SetlistAppService(session).add_setlist_track(
            playlist_id, payload.track_id, payload.position,
        )
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    if entry_id is None:
        raise HTTPException(404, "Local playlist not found")
    return {"setlist_track_id": entry_id}


@router.delete("/playlists/{playlist_id}/tracks/{entry_id}")
def remove_local_playlist_track(
    playlist_id: int, entry_id: int, session: Session = Depends(get_session),
):
    if not SetlistAppService(session).remove_setlist_track(playlist_id, entry_id):
        raise HTTPException(404, "Playlist entry not found")
    return {"ok": True}


@router.post("/rekordbox/import")
def import_rekordbox_mirror(payload: MirrorImport, session: Session = Depends(get_session)):
    playlist_ids = {item.external_id for item in payload.playlists}
    if len(playlist_ids) != len(payload.playlists):
        raise HTTPException(422, "Playlist external IDs must be unique")
    for item in payload.playlists:
        if item.parent_external_id and item.parent_external_id not in playlist_ids:
            raise HTTPException(400, f"Unknown parent playlist: {item.parent_external_id}")
    if any(member.playlist_external_id not in playlist_ids for member in payload.members):
        raise HTTPException(400, "A member references an unknown playlist")

    parents = {item.external_id: item.parent_external_id or None for item in payload.playlists}
    visited: set[str] = set()
    for playlist_id in playlist_ids:
        path: set[str] = set()
        current: str | None = playlist_id
        while current is not None and current not in visited:
            if current in path:
                raise HTTPException(422, f"Playlist parent cycle detected at: {current}")
            path.add(current)
            current = parents[current]
        visited.update(path)

    # Resolve against one library snapshot; playlists commonly repeat the same
    # tracks thousands of times across different sets.
    library = session.exec(text("SELECT id, filepath FROM tracks ORDER BY id")).all()
    local_ids = {int(row[0]) for row in library}
    paths: dict[str, int] = {}
    for track_id, filepath in library:
        if filepath:
            paths.setdefault(_normalized_filepath(filepath), int(track_id))
    normalized_paths: dict[str, str] = {}
    resolved = 0
    session.exec(text("DELETE FROM rekordbox_playlist_tracks WHERE source_id=:source"), params={"source": payload.source_id})
    session.exec(text("DELETE FROM rekordbox_playlists WHERE source_id=:source"), params={"source": payload.source_id})
    session.exec(text("""
        INSERT INTO rekordbox_sources (id, name, imported_at) VALUES (:id, :name, CURRENT_TIMESTAMP)
        ON CONFLICT (id) DO UPDATE SET name=excluded.name, imported_at=excluded.imported_at
    """), params={"id": payload.source_id, "name": payload.source_name})
    for item in payload.playlists:
        session.exec(text("""
            INSERT INTO rekordbox_playlists
            (source_id, external_id, parent_external_id, name, sort_order, kind)
            VALUES (:source, :id, :parent, :name, :sort, :kind)
        """), params={"source": payload.source_id, "id": item.external_id, "parent": item.parent_external_id or None,
                 "name": item.name, "sort": item.order, "kind": item.kind})
    for member in payload.members:
        local_id = member.local_track_id
        if local_id not in local_ids:
            local_id = None
        if local_id is None and member.filepath:
            if member.filepath not in normalized_paths:
                normalized_paths[member.filepath] = _normalized_filepath(member.filepath)
            local_id = paths.get(normalized_paths[member.filepath])
        resolved += int(local_id is not None)
        session.exec(text("""
            INSERT INTO rekordbox_playlist_tracks
            (source_id, playlist_external_id, position, external_track_id, local_track_id,
             filepath, title, artist, bpm, musical_key, duration)
            VALUES (:source, :playlist, :position, :external_track, :local, :filepath,
                    :title, :artist, :bpm, :key, :duration)
        """), params={"source": payload.source_id, "playlist": member.playlist_external_id,
                 "position": member.position, "external_track": member.external_track_id,
                 "local": local_id, "filepath": member.filepath, "title": member.title,
                 "artist": member.artist, "bpm": member.bpm, "key": member.key,
                 "duration": member.duration})
    session.commit()
    return {"source_id": payload.source_id, "playlists": len(payload.playlists),
            "members": len(payload.members), "resolved": resolved,
            "unmapped": len(payload.members) - resolved}


@router.get("/rekordbox/sources")
def mirror_sources(session: Session = Depends(get_session)):
    return _rows(session.exec(text("""
        SELECT s.id, s.name, s.imported_at, count(DISTINCT p.external_id) AS playlist_count,
               count(m.position) AS member_count,
               count(CASE WHEN m.position IS NOT NULL AND m.local_track_id IS NULL THEN 1 END) AS unmapped_count
        FROM rekordbox_sources s LEFT JOIN rekordbox_playlists p ON p.source_id=s.id
        LEFT JOIN rekordbox_playlist_tracks m ON m.source_id=p.source_id AND m.playlist_external_id=p.external_id
        GROUP BY s.id, s.name, s.imported_at ORDER BY s.name
    """)))


@router.get("/rekordbox/{source_id}/tree")
def mirror_tree(source_id: str, session: Session = Depends(get_session)):
    source = session.exec(text("SELECT id, name, imported_at FROM rekordbox_sources WHERE id=:id"), params={"id": source_id}).first()
    if not source:
        raise HTTPException(404, "Rekordbox mirror source not found")
    items = _rows(session.exec(text("""
        SELECT p.*, count(m.position) AS track_count,
               count(CASE WHEN m.position IS NOT NULL AND m.local_track_id IS NULL THEN 1 END) AS unmapped_count
        FROM rekordbox_playlists p LEFT JOIN rekordbox_playlist_tracks m
          ON m.source_id=p.source_id AND m.playlist_external_id=p.external_id
        WHERE p.source_id=:id GROUP BY p.source_id,p.external_id,p.parent_external_id,p.name,p.sort_order,p.kind
        ORDER BY p.sort_order,p.name
    """), params={"id": source_id}))
    return {"source": dict(source._mapping), "items": items}


@router.get("/rekordbox/{source_id}/tree/page")
def mirror_tree_page(
    source_id: str,
    parent_external_id: str | None = None,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    session: Session = Depends(get_session),
):
    source = session.exec(text(
        "SELECT id,name,imported_at FROM rekordbox_sources WHERE id=:id"
    ), params={"id": source_id}).first()
    if not source:
        raise HTTPException(404, "Rekordbox mirror source not found")
    params = {"source": source_id, "parent": parent_external_id, "limit": limit, "offset": offset}
    total = int(session.exec(text("""
        SELECT count(*) FROM rekordbox_playlists
        WHERE source_id=:source AND parent_external_id IS NOT DISTINCT FROM :parent
    """), params=params).one()[0])
    items = _rows(session.exec(text("""
        SELECT p.*, false AS editable, 'rekordbox' AS source,
               (SELECT count(*) FROM rekordbox_playlist_tracks m
                WHERE m.source_id=p.source_id AND m.playlist_external_id=p.external_id) AS track_count,
               (SELECT count(*) FROM rekordbox_playlist_tracks m LEFT JOIN tracks t ON t.id=m.local_track_id
                WHERE m.source_id=p.source_id AND m.playlist_external_id=p.external_id
                  AND t.id IS NULL) AS unmapped_count,
               (SELECT count(*) FROM rekordbox_playlists c
                WHERE c.source_id=p.source_id AND c.parent_external_id=p.external_id) AS child_count
        FROM rekordbox_playlists p
        WHERE p.source_id=:source AND p.parent_external_id IS NOT DISTINCT FROM :parent
        ORDER BY p.sort_order,p.name,p.external_id LIMIT :limit OFFSET :offset
    """), params=params))
    return {"source": dict(source._mapping), "items": items, "total": total,
            "limit": limit, "offset": offset, "has_more": offset + len(items) < total}


@router.get("/rekordbox/{source_id}/playlists/{playlist_id}/tracks")
def mirror_tracks(source_id: str, playlist_id: str, session: Session = Depends(get_session)):
    return _rows(session.exec(text("""
        SELECT m.position,m.external_track_id,m.local_track_id,m.filepath AS source_filepath,
               coalesce(t.title,m.title,'') AS title,coalesce(t.artist,m.artist,'') AS artist,
               coalesce(t.bpm,m.bpm) AS bpm,coalesce(t.key,m.musical_key,'') AS key,
               coalesce(t.duration,m.duration,0) AS duration,t.filepath,t.album,t.genre,t.subgenre,
               t.scale,t.energy,t.danceability,t.loudness,t.brightness,t.noisiness,t.contrast,
               t.loudness_range,t.spectral_flux,t.spectral_rolloff,t.is_genre_verified,t.created_at,
               (t.id IS NOT NULL) AS resolved
        FROM rekordbox_playlist_tracks m LEFT JOIN tracks t ON t.id=m.local_track_id
        WHERE m.source_id=:source AND m.playlist_external_id=:playlist ORDER BY m.position
    """), params={"source": source_id, "playlist": playlist_id}))


@router.get("/rekordbox/{source_id}/playlists/{playlist_id}/tracks/page")
def mirror_tracks_page(
    source_id: str, playlist_id: str,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    session: Session = Depends(get_session),
):
    params = {"source": source_id, "playlist": playlist_id, "limit": limit, "offset": offset}
    exists = session.exec(text("""
        SELECT 1 FROM rekordbox_playlists WHERE source_id=:source AND external_id=:playlist
    """), params=params).first()
    if not exists:
        raise HTTPException(404, "Rekordbox mirror playlist not found")
    total = int(session.exec(text("""
        SELECT count(*) FROM rekordbox_playlist_tracks
        WHERE source_id=:source AND playlist_external_id=:playlist
    """), params=params).one()[0])
    items = _rows(session.exec(text("""
        SELECT m.position,m.external_track_id,m.local_track_id,m.filepath AS source_filepath,
               coalesce(t.title,m.title,'') AS title,coalesce(t.artist,m.artist,'') AS artist,
               coalesce(t.bpm,m.bpm) AS bpm,coalesce(t.key,m.musical_key,'') AS key,
               coalesce(t.duration,m.duration,0) AS duration,t.filepath,t.album,t.genre,t.subgenre,
               t.scale,t.energy,t.danceability,t.loudness,t.brightness,t.noisiness,t.contrast,
               t.loudness_range,t.spectral_flux,t.spectral_rolloff,t.is_genre_verified,t.created_at,
               (t.id IS NOT NULL) AS resolved
        FROM rekordbox_playlist_tracks m LEFT JOIN tracks t ON t.id=m.local_track_id
        WHERE m.source_id=:source AND m.playlist_external_id=:playlist
        ORDER BY m.position LIMIT :limit OFFSET :offset
    """), params=params))
    return {"items": items, "total": total, "limit": limit, "offset": offset,
            "has_more": offset + len(items) < total}


@router.post("/rekordbox/{source_id}/playlists/{playlist_id}/copy")
def copy_mirror_playlist(
    source_id: str, playlist_id: str, payload: MirrorPlaylistCopy,
    session: Session = Depends(get_session),
):
    source = session.exec(text("""
        SELECT name FROM rekordbox_playlists WHERE source_id=:source AND external_id=:playlist
    """), params={"source": source_id, "playlist": playlist_id}).first()
    if not source:
        raise HTTPException(404, "Rekordbox mirror playlist not found")
    name = payload.name.strip() if payload.name else str(source[0])
    try:
        local_id = int(session.exec(text(
            "INSERT INTO setlists (name) VALUES (:name) RETURNING id"
        ), params={"name": name}).one()[0])
        params = {"source": source_id, "playlist": playlist_id, "setlist": local_id}
        total = int(session.exec(text("""
            SELECT count(*) FROM rekordbox_playlist_tracks
            WHERE source_id=:source AND playlist_external_id=:playlist
        """), params=params).one()[0])
        copied = int(session.exec(text("""
            SELECT count(*) FROM rekordbox_playlist_tracks m JOIN tracks t ON t.id=m.local_track_id
            WHERE m.source_id=:source AND m.playlist_external_id=:playlist
        """), params=params).one()[0])
        session.exec(text("""
            INSERT INTO setlist_tracks (setlist_id,track_id,position)
            SELECT :setlist,m.local_track_id,row_number() OVER (ORDER BY m.position)-1
            FROM rekordbox_playlist_tracks m JOIN tracks t ON t.id=m.local_track_id
            WHERE m.source_id=:source AND m.playlist_external_id=:playlist
            ORDER BY m.position
        """), params=params)
        session.commit()
    except Exception:
        session.rollback()
        raise
    local = session.get(Setlist, local_id)
    result = local.model_dump(mode="json")
    result.update({"source": "plumdeck", "editable": True, "track_count": copied})
    return {"playlist": result, "copied": copied, "skipped_unresolved": total - copied}


@router.post("/sessions")
def start_session(payload: PlaySessionCreate, session: Session = Depends(get_session)):
    session.exec(text("""
        INSERT INTO play_sessions (id,deck_count) VALUES (:id,:count)
        ON CONFLICT (id) DO UPDATE SET deck_count=excluded.deck_count,ended_at=NULL
    """), params={"id": payload.id, "count": payload.deck_count})
    session.commit()
    return {"id": payload.id, "deck_count": payload.deck_count}


@router.post("/sessions/{session_id}/end")
def end_session(session_id: str, session: Session = Depends(get_session)):
    session.exec(text("UPDATE play_sessions SET ended_at=CURRENT_TIMESTAMP WHERE id=:id"), params={"id": session_id})
    session.commit()
    return {"id": session_id, "ended": True}


@router.put("/history")
def upsert_history(payload: HistoryUpsert, session: Session = Depends(get_session)):
    values = payload.model_dump()
    values["loaded_at"] = values["loaded_at"] or datetime.now()
    session.exec(text("""
        INSERT INTO play_history (event_key,session_id,deck,track_id,loaded_at,first_played_at,ended_at,played_ms,completed,reason)
        VALUES (:event_key,:session_id,:deck,:track_id,:loaded_at,:first_played_at,:ended_at,:played_ms,:completed,:reason)
        ON CONFLICT (event_key) DO UPDATE SET
          first_played_at=coalesce(play_history.first_played_at,excluded.first_played_at),
          ended_at=CASE WHEN play_history.completed THEN play_history.ended_at
                        ELSE coalesce(excluded.ended_at,play_history.ended_at) END,
          played_ms=CASE WHEN play_history.completed THEN play_history.played_ms
                         ELSE greatest(play_history.played_ms,excluded.played_ms) END,
          completed=play_history.completed OR excluded.completed,
          reason=CASE WHEN play_history.completed THEN play_history.reason
                      ELSE coalesce(excluded.reason,play_history.reason) END
    """), params=values)
    session.commit()
    return {"event_key": payload.event_key}


@router.get("/history")
def history(limit: int = Query(100, ge=1, le=500), session: Session = Depends(get_session)):
    return _rows(session.exec(text("""
        SELECT h.*,t.title,t.artist,t.filepath,t.bpm,t.key,t.genre,t.duration
        FROM play_history h LEFT JOIN tracks t ON t.id=h.track_id
        ORDER BY coalesce(h.first_played_at,h.loaded_at) DESC LIMIT :limit
    """), params={"limit": limit}))


@router.put("/recordings")
@_serialize_recording_mutation
def upsert_recording(payload: RecordingUpsert, session: Session = Depends(get_session)):
    session.exec(text("""
        INSERT INTO recordings (recording_key,session_id,filepath,started_at,ended_at,duration_ms,status,error,
          sample_rate_hz,frame_count,timeline_quality,timeline_dropped_events)
        VALUES (:recording_key,:session_id,:filepath,:started_at,:ended_at,:duration_ms,:status,:error,
          :sample_rate_hz,:frame_count,:timeline_quality,:timeline_dropped_events)
        ON CONFLICT (recording_key) DO UPDATE SET
          session_id=coalesce(recordings.session_id,excluded.session_id),
          filepath=CASE WHEN recordings.status IN ('completed','failed') THEN recordings.filepath
                        WHEN excluded.filepath <> '' THEN excluded.filepath ELSE recordings.filepath END,
          started_at=least(recordings.started_at,excluded.started_at),
          ended_at=CASE WHEN recordings.status IN ('completed','failed') THEN recordings.ended_at
                        ELSE coalesce(excluded.ended_at,recordings.ended_at) END,
          duration_ms=greatest(recordings.duration_ms,excluded.duration_ms),
          status=CASE WHEN recordings.status IN ('completed','failed') THEN recordings.status
                      ELSE excluded.status END,
          error=CASE WHEN recordings.status IN ('completed','failed') THEN recordings.error
                     ELSE excluded.error END,
          sample_rate_hz=coalesce(excluded.sample_rate_hz,recordings.sample_rate_hz),
          frame_count=greatest(coalesce(recordings.frame_count,0),coalesce(excluded.frame_count,0)),
          timeline_quality=CASE WHEN excluded.timeline_quality='not_recorded' THEN recordings.timeline_quality ELSE excluded.timeline_quality END,
          timeline_dropped_events=greatest(recordings.timeline_dropped_events,excluded.timeline_dropped_events)
    """), params=payload.model_dump())
    session.commit()
    row = session.exec(text("SELECT id FROM recordings WHERE recording_key=:key"), params={"key": payload.recording_key}).one()
    return {"recording_key": payload.recording_key, "id": int(row[0])}


def _recording_file(session: Session, recording_id: int) -> tuple[dict, Path]:
    """録音行と、その音声ファイル。DB のパスをそのまま配らないよう実体を確かめる。"""
    rows = _rows(session.exec(text("SELECT * FROM recordings WHERE id=:id"), params={"id": recording_id}))
    if not rows:
        raise HTTPException(404, "録音が見つかりません")
    row = rows[0]
    if row.get("status") == "recording":
        raise HTTPException(409, "録音ファイルを書き込み中です。録音を停止してから再試行してください。")
    path = Path(str(row.get("filepath") or "")).expanduser()
    if path.suffix.lower() not in _RECORDING_MEDIA_TYPES or not path.is_file():
        raise HTTPException(404, "録音ファイルが見つかりません")
    return row, path


def _ffmpeg_path() -> str | None:
    """Find FFmpeg even when a macOS GUI launch supplies a minimal PATH."""
    bundle_root = getattr(sys, "_MEIPASS", None)
    if bundle_root:
        bundled = Path(bundle_root) / "bin" / "ffmpeg"
        if bundled.is_file() and os.access(bundled, os.X_OK):
            return str(bundled)
    executable = shutil.which("ffmpeg")
    if executable:
        return executable
    return next((str(candidate) for candidate in (
        Path("/opt/homebrew/bin/ffmpeg"), Path("/usr/local/bin/ffmpeg"),
    ) if candidate.is_file() and os.access(candidate, os.X_OK)), None)


@lru_cache(maxsize=1)
def _probe_recording_formats(executable: str) -> tuple[str, ...]:
    # A first translated macOS launch can spend time validating bundled dylibs.
    # Cache successful probes only, allowing a failed first launch to retry.
    probe = subprocess.run(
        [executable, "-hide_banner", "-encoders"], capture_output=True, text=True,
        timeout=180, check=True,
    )
    words = set(probe.stdout.split())
    return tuple(name for name, details in _EXPORT_FORMATS.items() if details["encoder"] in words)


def _available_recording_formats() -> tuple[str, ...]:
    executable = _ffmpeg_path()
    if not executable:
        return ()
    try:
        return _probe_recording_formats(executable)
    except (OSError, subprocess.SubprocessError):
        return ()


@router.get("/recordings/formats")
def recording_formats():
    """Return only export formats backed by an encoder available right now."""
    return {"formats": [
        {"value": name, "extension": _EXPORT_FORMATS[name]["extension"],
         "label": _EXPORT_FORMATS[name]["label"]}
        for name in _available_recording_formats()
    ]}


@router.get("/recordings/{recording_id}/audio")
def recording_audio(recording_id: int, session: Session = Depends(get_session)):
    """保存前に聴いて確かめるための再生用。"""
    _, path = _recording_file(session, recording_id)
    return FileResponse(
        path, media_type=_RECORDING_MEDIA_TYPES[path.suffix.lower()],
        headers={"Cache-Control": "no-store"},
    )


def _converted_recording(path: Path, target: Path, export_format: str) -> Path:
    executable = _ffmpeg_path()
    details = _EXPORT_FORMATS[export_format]
    if not executable or export_format not in _available_recording_formats():
        raise HTTPException(503, f"{export_format.upper()} の書き出しに必要なエンコーダーを利用できません")
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{target.stem}-", suffix=str(details["extension"]), dir=target.parent,
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    temporary.unlink(missing_ok=True)
    command = [
        executable, "-nostdin", "-v", "error", "-i", str(path), "-vn",
        "-c:a", str(details["encoder"]), str(temporary),
    ]
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=1800, check=False)
        if result.returncode != 0 or not temporary.is_file() or temporary.stat().st_size == 0:
            message = result.stderr.strip().splitlines()[-1] if result.stderr.strip() else "変換結果が空です"
            raise HTTPException(422, f"録音を {export_format.upper()} に変換できません: {message}")
        # The temporary is in the same directory. Linking is an atomic no-clobber
        # promotion: a target created while FFmpeg ran is never overwritten.
        try:
            os.link(temporary, target)
        except FileExistsError as exc:
            raise HTTPException(409, f"同じ名前のファイルが既にあります: {target.name}") from exc
        return target
    except subprocess.TimeoutExpired as exc:
        raise HTTPException(504, "録音の変換がタイムアウトしました") from exc
    except OSError as exc:
        raise HTTPException(500, f"録音ファイルを書き出せません: {exc}") from exc
    finally:
        temporary.unlink(missing_ok=True)


@router.patch("/recordings/{recording_id}")
@_serialize_recording_mutation
def name_recording(recording_id: int, payload: RecordingName, session: Session = Depends(get_session)):
    """アーティスト名とミックス名を付けて確定する。ファイル名もそれに合わせる。"""
    row, path = _recording_file(session, recording_id)
    artist, title = payload.artist.strip(), payload.title.strip()
    if not title:
        raise HTTPException(422, "ミックス名を入力してください")
    stem = f"{artist} - {title}" if artist else title
    # ファイル名に使えない文字を落とす。空になったら元の名前を保つ。
    safe = "".join("_" if character in '/\\:*?"<>|' else character for character in stem).strip(" .")
    suffix = str(_EXPORT_FORMATS[payload.format]["extension"]) if payload.format else path.suffix.lower()
    target = path.with_name(f"{safe}{suffix}") if safe else path.with_suffix(suffix)
    promoted = False
    if target != path:
        if target.exists():
            raise HTTPException(409, f"同じ名前のファイルが既にあります: {target.name}")
        if target.suffix.lower() == path.suffix.lower():
            try:
                # Keep the original until the database points at the new name.
                # link() also refuses a target created after the exists check.
                os.link(path, target)
            except FileExistsError as exc:
                raise HTTPException(409, f"同じ名前のファイルが既にあります: {target.name}") from exc
            except OSError as exc:
                raise HTTPException(500, f"録音ファイルの名前を変更できません: {exc}") from exc
        else:
            _converted_recording(path, target, payload.format or target.suffix.removeprefix("."))
        promoted = True
    try:
        session.exec(text("UPDATE recordings SET artist=:artist,title=:title,filepath=:filepath WHERE id=:id"),
                     params={"artist": artist or None, "title": title, "filepath": str(target), "id": recording_id})
        session.commit()
    except Exception:
        session.rollback()
        if promoted and path.is_file():
            try:
                target.unlink(missing_ok=True)
            except OSError:
                pass
        raise
    if promoted:
        # The database and converted output are durable before the source is removed.
        try:
            path.unlink(missing_ok=True)
        except OSError:
            # A harmless duplicate is preferable to reporting that a committed
            # export failed or risking the newly converted recording.
            pass
    return {**row, "artist": artist or None, "title": title, "filepath": str(target)}


@router.delete("/recordings/{recording_id}")
@_serialize_recording_mutation
def discard_recording(recording_id: int, session: Session = Depends(get_session)):
    """要らない録音を音声ごと捨てる。"""
    rows = _rows(session.exec(text("SELECT * FROM recordings WHERE id=:id"), params={"id": recording_id}))
    if not rows:
        raise HTTPException(404, "録音が見つかりません")
    if rows[0].get("status") == "recording":
        raise HTTPException(409, "録音中のファイルは破棄できません。先に録音を停止してください。")
    path = Path(str(rows[0].get("filepath") or "")).expanduser()
    if path.suffix.lower() in _RECORDING_MEDIA_TYPES and path.is_file():
        path.unlink(missing_ok=True)
    session.exec(text("DELETE FROM recordings WHERE id=:id"), params={"id": recording_id})
    session.commit()
    return {"deleted": recording_id}


@router.get("/recordings")
def recordings(limit: int = Query(100, ge=1, le=500), session: Session = Depends(get_session)):
    return _rows(session.exec(text("SELECT * FROM recordings ORDER BY started_at DESC LIMIT :limit"), params={"limit": limit}))
