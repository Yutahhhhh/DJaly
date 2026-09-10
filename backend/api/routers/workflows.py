from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, BackgroundTasks, Body, Depends, HTTPException, Query
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlmodel import Session
from mutagen import File as MutagenFile

from app.services.play_import_service import PlayImportService, process_batch
from app.services.workflow_service import (
    MediaRepairService, PresetService, RecordingTimelineService, UsbHandoffService,
    VersionService, create_backup, inspect_backup, restore_backup,
)
from infra.database.connection import get_session


router = APIRouter(prefix="/api/workflows", tags=["library-workflows"])
EXTERNAL_RECORDING_EXTENSIONS = {".wav", ".wave", ".aif", ".aiff", ".flac", ".mp3", ".ogg", ".oga"}


def _error(exc: ValueError, status: int = 422):
    raise HTTPException(status_code=status, detail=str(exc)) from exc


class RepairPlanRequest(BaseModel):
    track_ids: list[int] | None = None
    old_root: str | None = None
    new_root: str | None = None


class RepairApplyRequest(BaseModel):
    selections: dict[str, str]


class VersionCreateRequest(BaseModel):
    track_ids: list[int]
    name: str | None = Field(default=None, max_length=200)
    labels: dict[str, dict[str, str]] | None = None


class VersionUpdateRequest(BaseModel):
    revision: int
    name: str | None = Field(default=None, max_length=200)
    preferred_track_id: int | None = None
    members: list[dict[str, Any]] | None = None


class VersionSwapRequest(BaseModel):
    new_track_id: int
    revision: int


class BackupCreateRequest(BaseModel):
    destination: str
    include_media: bool = False
    include_recordings: bool = False
    ui_settings: dict[str, Any] = {}


class RestoreRequest(BaseModel):
    path: str
    confirmed: bool = False


class AudioPresetRequest(BaseModel):
    id: str | None = None
    revision: int | None = None
    name: str
    config: dict[str, Any]


class UsbHandoffRequest(BaseModel):
    setlist_id: int
    usb_device_id: str | None = None


class UsbDuplicateRequest(BaseModel):
    usb_device_id: str | None = None


class UsbVerifyRequest(BaseModel):
    level: Literal["user_rekordbox_check", "user_hardware_check"]
    model: str | None = None
    firmware: str | None = None
    checked_at: str | None = None
    checks: list[str] | None = None
    notes: str | None = None


class ImportTarget(BaseModel):
    kind: Literal["collection", "local_playlist"]
    id: int | None = None


class PlayImportRequest(BaseModel):
    request_id: str = Field(min_length=1, max_length=200)
    target: ImportTarget
    paths: list[str] = Field(min_length=1, max_length=2000)
    origin: Literal["native_file_drop", "file_picker"] = "native_file_drop"


class ManualTimelineRequest(BaseModel):
    revision: int
    segments: list[dict[str, Any]] = Field(max_length=5000)


class EngineTimelineRequest(BaseModel):
    sample_rate_hz: int = Field(ge=8000, le=384000)
    frame_count: int = Field(ge=0)
    dropped_events: int = Field(default=0, ge=0)
    segments: list[dict[str, Any]] = Field(max_length=10_000)


class ExternalRecordingRequest(BaseModel):
    filepath: str
    title: str = Field(min_length=1, max_length=200)
    artist: str = Field(default="", max_length=200)
    duration_ms: int | None = Field(default=None, gt=0)


@router.get("/summary")
def summary(session: Session = Depends(get_session)):
    names = ("track_media", "track_version_groups", "audio_presets", "controller_profiles",
             "usb_exports", "recording_segments", "import_batches")
    return {name: int(session.exec(text(f'SELECT count(*) FROM "{name}"')).one()[0]) for name in names}


@router.post("/media/diagnose")
def diagnose_media(payload: RepairPlanRequest, session: Session = Depends(get_session)):
    try:
        return MediaRepairService(session).diagnose(payload.track_ids, payload.old_root, payload.new_root)
    except ValueError as exc:
        _error(exc)


@router.post("/media/repairs/{plan_id}/apply")
def apply_media_repair(plan_id: str, payload: RepairApplyRequest, session: Session = Depends(get_session)):
    try:
        return MediaRepairService(session).apply(plan_id, payload.selections)
    except ValueError as exc:
        _error(exc, 409)


@router.post("/media/repairs/{plan_id}/undo")
def undo_media_repair(plan_id: str, session: Session = Depends(get_session)):
    try:
        return MediaRepairService(session).undo(plan_id)
    except ValueError as exc:
        _error(exc, 409)


@router.post("/version-groups")
def create_version_group(payload: VersionCreateRequest, session: Session = Depends(get_session)):
    try:
        return VersionService(session).create(payload.track_ids, payload.name, payload.labels)
    except ValueError as exc:
        _error(exc, 409)


@router.get("/tracks/{track_id}/versions")
def versions_for_track(track_id: int, session: Session = Depends(get_session)):
    return VersionService(session).for_track(track_id)


@router.patch("/version-groups/{group_id}")
def update_version_group(group_id: int, payload: VersionUpdateRequest, session: Session = Depends(get_session)):
    try:
        return VersionService(session).update(group_id, **payload.model_dump())
    except ValueError as exc:
        _error(exc, 409)


@router.patch("/setlist-entries/{entry_id}/version")
def swap_setlist_version(entry_id: int, payload: VersionSwapRequest, session: Session = Depends(get_session)):
    try:
        return VersionService(session).swap_entry(entry_id, payload.new_track_id, payload.revision)
    except ValueError as exc:
        _error(exc, 409)


@router.post("/backups")
def backup(payload: BackupCreateRequest, session: Session = Depends(get_session)):
    try:
        return create_backup(session, **payload.model_dump())
    except (ValueError, OSError) as exc:
        _error(ValueError(str(exc)))


@router.post("/restore/inspect")
def restore_inspect(path: str = Body(embed=True)):
    try:
        return inspect_backup(path)
    except (ValueError, OSError) as exc:
        _error(ValueError(str(exc)))


@router.post("/restore/apply")
def restore_apply(payload: RestoreRequest):
    try:
        return restore_backup(payload.path, payload.confirmed)
    except (ValueError, OSError) as exc:
        _error(ValueError(str(exc)), 409)


@router.get("/audio-presets")
def audio_presets(session: Session = Depends(get_session)):
    return PresetService(session).audio_list()


@router.put("/audio-presets")
def save_audio_preset(payload: AudioPresetRequest, session: Session = Depends(get_session)):
    try:
        return PresetService(session).save_audio(payload.model_dump())
    except ValueError as exc:
        _error(exc, 409)


@router.delete("/audio-presets/{preset_id}")
def delete_audio_preset(preset_id: str, session: Session = Depends(get_session)):
    if not PresetService(session).delete_audio(preset_id):
        raise HTTPException(404, "プリセットが見つかりません")
    return {"deleted": preset_id}


@router.get("/controller-profiles")
def controller_profiles(session: Session = Depends(get_session)):
    return PresetService(session).controllers()


@router.put("/controller-profiles")
def save_controller_profile(payload: dict[str, Any], session: Session = Depends(get_session)):
    try:
        return PresetService(session).save_controller(payload)
    except ValueError as exc:
        _error(exc, 422)


@router.post("/usb/handoffs")
def create_usb_handoff(payload: UsbHandoffRequest, session: Session = Depends(get_session)):
    try:
        return UsbHandoffService(session).create(payload.setlist_id, payload.usb_device_id)
    except ValueError as exc:
        _error(exc, 409)


@router.get("/usb/devices")
def list_usb_devices(session: Session = Depends(get_session)):
    return UsbHandoffService(session).devices()


@router.post("/usb/devices/{device_id}/eject")
def eject_usb_device(device_id: str, session: Session = Depends(get_session)):
    try:
        return UsbHandoffService(session).eject(device_id)
    except ValueError as exc:
        _error(exc, 409)


@router.get("/usb/handoffs")
def list_usb_handoffs(session: Session = Depends(get_session)):
    return UsbHandoffService(session).list()


@router.post("/usb/handoffs/{export_id}/duplicate")
def duplicate_usb_handoff(export_id: str, payload: UsbDuplicateRequest,
                          session: Session = Depends(get_session)):
    try:
        return UsbHandoffService(session).duplicate(export_id, payload.usb_device_id)
    except ValueError as exc:
        _error(exc, 409)


@router.post("/usb/handoffs/{export_id}/verify")
def verify_usb_handoff(export_id: str, payload: UsbVerifyRequest, session: Session = Depends(get_session)):
    try:
        return UsbHandoffService(session).mark_checked(export_id, payload.model_dump(exclude_none=True))
    except ValueError as exc:
        _error(exc, 422)


@router.post("/play/imports", status_code=202)
def create_play_import(payload: PlayImportRequest, background: BackgroundTasks,
                       session: Session = Depends(get_session)):
    try:
        result = PlayImportService(session).create(
            payload.request_id, payload.target.kind, payload.target.id, payload.paths, payload.origin,
        )
        if result["state"] in {"queued", "paused"}:
            background.add_task(process_batch, result["id"])
        return result
    except ValueError as exc:
        _error(exc, 409)


@router.get("/play/imports")
def list_play_imports(active: bool = Query(False), session: Session = Depends(get_session)):
    return PlayImportService(session).list(active)


@router.get("/play/imports/{batch_id}")
def get_play_import(batch_id: str, session: Session = Depends(get_session)):
    try:
        return PlayImportService(session).get(batch_id)
    except ValueError as exc:
        _error(exc, 404)


@router.post("/play/imports/{batch_id}/{action}")
def control_play_import(batch_id: str, action: Literal["pause", "resume", "cancel", "retry"],
                        background: BackgroundTasks, session: Session = Depends(get_session)):
    try:
        result = PlayImportService(session).set_state(batch_id, action)
        if action in {"resume", "retry"}:
            background.add_task(process_batch, batch_id)
        return result
    except ValueError as exc:
        _error(exc, 409)


@router.get("/recordings/{recording_id}/timeline")
def recording_timeline(recording_id: int, session: Session = Depends(get_session)):
    return RecordingTimelineService(session).list(recording_id)


@router.put("/recordings/{recording_id}/timeline")
def replace_recording_timeline(recording_id: int, payload: ManualTimelineRequest,
                               session: Session = Depends(get_session)):
    try:
        return RecordingTimelineService(session).replace_manual(recording_id, payload.revision, payload.segments)
    except ValueError as exc:
        _error(exc, 409)


@router.post("/recordings/{recording_id}/timeline/engine")
def upsert_recording_engine_timeline(recording_id: int, payload: EngineTimelineRequest,
                                     session: Session = Depends(get_session)):
    try:
        return RecordingTimelineService(session).upsert_engine(recording_id, **payload.model_dump())
    except ValueError as exc:
        _error(exc, 409)


@router.get("/recordings/{recording_id}/tracklist.txt", response_class=PlainTextResponse)
def recording_tracklist(recording_id: int, session: Session = Depends(get_session)):
    return RecordingTimelineService(session).text(recording_id)


@router.post("/recordings/external")
def register_external_recording(payload: ExternalRecordingRequest, session: Session = Depends(get_session)):
    path = Path(payload.filepath).expanduser()
    if not path.is_absolute() or not path.is_file():
        raise HTTPException(422, "録音ファイルが見つかりません")
    if path.suffix.casefold() not in EXTERNAL_RECORDING_EXTENSIONS:
        raise HTTPException(422, "録音ライブラリで再生できない音声形式です")
    try:
        media = MutagenFile(path)
        duration_ms = round(float(media.info.length) * 1000) if media and media.info else 0
    except Exception as exc:
        raise HTTPException(422, "録音ファイルを読み取れません") from exc
    if duration_ms <= 0:
        raise HTTPException(422, "録音ファイルの長さを確認できません")
    key = f"external:{uuid.uuid4()}"
    row = session.exec(text("""
        INSERT INTO recordings (recording_key,filepath,started_at,ended_at,duration_ms,status,artist,title,source)
        VALUES (:key,:path,:started,:ended,:duration,'completed',:artist,:title,'external') RETURNING id
    """), params={"key": key, "path": str(path.resolve()), "started": datetime.now(timezone.utc),
                    "ended": datetime.now(timezone.utc), "duration": duration_ms,
                    "artist": payload.artist, "title": payload.title}).one()
    session.commit()
    return {"id": int(row[0]), "recording_key": key, "duration_ms": duration_ms}
