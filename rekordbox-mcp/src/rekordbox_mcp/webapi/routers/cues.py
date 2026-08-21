"""Cue management REST API."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from rekordbox_mcp.db.xml_writer import RekordboxXmlWriter
from rekordbox_mcp.domain.beatgrid import BeatGrid as BeatGridDomain
from rekordbox_mcp.domain.cue import CueManager, create_cue_position
from rekordbox_mcp.domain.models import OperationMode
from rekordbox_mcp.mcp.server import get_cue_strategy, get_repository, get_settings_instance
from rekordbox_mcp.webapi.deps import check_write_mode

router = APIRouter(prefix="/api/cues", tags=["cues"])


def _get_track_with_analysis(track_id: int) -> Any:
    repo = get_repository()
    track = repo.get_track(track_id)
    if not track:
        raise HTTPException(status_code=404, detail=f"Track {track_id} not found")
    if not track.beat_grid:
        raise HTTPException(status_code=400, detail=f"Track {track_id} has no beat grid (BPM not analyzed)")
    return track


def _get_domain_beat_grid(track: Any) -> BeatGridDomain:
    """Convert the API model beat grid to the domain representation."""
    return BeatGridDomain.from_model(track.beat_grid)


def _persist_cues(track: Any, cues: list[Any], mode: OperationMode) -> list[Any]:
    """Persist newly added cues using the selected write backend."""
    repo = get_repository()
    if mode == OperationMode.XML:
        path = get_settings_instance().xml_path_obj
        path.parent.mkdir(parents=True, exist_ok=True)
        writer = RekordboxXmlWriter(path)
        writer.sync_cues_for_track(track, cues)
        writer.save(path)
        return cues
    return [repo.add_cue(track.id, cue) for cue in cues]


def _persist_xml_cues(track: Any, cues: list[Any]) -> None:
    """Replace all cues for a track in the collection XML."""
    path = get_settings_instance().xml_path_obj
    path.parent.mkdir(parents=True, exist_ok=True)
    writer = RekordboxXmlWriter(path)
    writer.sync_cues_for_track(track, cues)
    writer.save(path)


class AddHotCueRequest(BaseModel):
    track_id: int
    position_ms: float | None = None
    kind: int = 1
    name: str = ""
    color_table_index: int | None = None
    loop_end_ms: float | None = None
    beat: int | None = None
    bar: int | None = None
    relative_to_cue_id: str | None = None
    relative_offset_ms: float = 0.0
    relative_offset_beats: float = 0.0
    relative_offset_bars: float = 0.0
    snap: Literal["none", "beat", "bar", "half_beat", "quarter_beat"] = "beat"


class AddMemoryCueRequest(BaseModel):
    track_id: int
    position_ms: float | None = None
    name: str = ""
    color: int = 0
    loop_end_ms: float | None = None
    beat: int | None = None
    bar: int | None = None
    relative_to_cue_id: str | None = None
    relative_offset_ms: float = 0.0
    relative_offset_beats: float = 0.0
    relative_offset_bars: float = 0.0
    snap: Literal["none", "beat", "bar", "half_beat", "quarter_beat"] = "beat"


class AddLoopRequest(BaseModel):
    track_id: int
    position_ms: float | None = None
    loop_end_ms: float
    kind: int = 2
    name: str = ""
    beat: int | None = None
    bar: int | None = None
    relative_to_cue_id: str | None = None
    relative_offset_ms: float = 0.0
    relative_offset_beats: float = 0.0
    relative_offset_bars: float = 0.0
    snap: Literal["none", "beat", "bar", "half_beat", "quarter_beat"] = "beat"


class UpdateCueRequest(BaseModel):
    track_id: int
    position_ms: float | None = None
    name: str | None = None
    color_table_index: int | None = None
    color: int | None = None
    loop_end_ms: float | None = None
    beat: int | None = None
    bar: int | None = None
    relative_to_cue_id: str | None = None
    relative_offset_ms: float = 0.0
    relative_offset_beats: float = 0.0
    relative_offset_bars: float = 0.0
    snap: Literal["none", "beat", "bar", "half_beat", "quarter_beat"] = "beat"


class GenerateCuesRequest(BaseModel):
    profile: str = "default"
    mode: Literal["replace", "merge", "preserve"] = "replace"


@router.get("/{track_id}")
async def get_cues(track_id: int) -> dict[str, Any]:
    """Get all cue points for a track."""
    repo = get_repository()
    cues = repo.get_cues(track_id)
    return {
        "track_id": track_id,
        "cues": [cue.model_dump(mode="json") for cue in cues],
        "hot_cues": [c.model_dump(mode="json") for c in cues if c.is_hot_cue],
        "memory_cues": [c.model_dump(mode="json") for c in cues if c.is_memory_cue],
        "loops": [c.model_dump(mode="json") for c in cues if c.is_loop],
    }


@router.post("/hot")
async def add_hot_cue(body: AddHotCueRequest) -> dict[str, Any]:
    """Add a hot cue to a track."""
    mode = check_write_mode()

    track = _get_track_with_analysis(body.track_id)
    beat_grid = _get_domain_beat_grid(track)

    repo = get_repository()
    existing_cues = repo.get_cues(body.track_id)
    cue_manager = CueManager(body.track_id, beat_grid, existing_cues)

    position = create_cue_position(
        position_ms=body.position_ms, beat=body.beat, bar=body.bar,
        relative_to_cue_id=body.relative_to_cue_id,
        relative_offset_ms=body.relative_offset_ms,
        relative_offset_beats=body.relative_offset_beats,
        relative_offset_bars=body.relative_offset_bars, snap=body.snap,
    )

    cue = cue_manager.add_hot_cue(
        position=position,
        kind=body.kind,
        name=body.name,
        color_table_index=body.color_table_index,
        loop_end=create_cue_position(position_ms=body.loop_end_ms, snap="beat") if body.loop_end_ms else None,
    )

    saved_cue = _persist_cues(track, [cue], mode)[0]

    return {"success": True, "cue": saved_cue.model_dump(mode="json")}


@router.post("/memory")
async def add_memory_cue(body: AddMemoryCueRequest) -> dict[str, Any]:
    """Add a memory cue to a track."""
    mode = check_write_mode()

    track = _get_track_with_analysis(body.track_id)
    beat_grid = _get_domain_beat_grid(track)

    repo = get_repository()
    existing_cues = repo.get_cues(body.track_id)
    cue_manager = CueManager(body.track_id, beat_grid, existing_cues)

    position = create_cue_position(
        position_ms=body.position_ms, beat=body.beat, bar=body.bar,
        relative_to_cue_id=body.relative_to_cue_id,
        relative_offset_ms=body.relative_offset_ms,
        relative_offset_beats=body.relative_offset_beats,
        relative_offset_bars=body.relative_offset_bars, snap=body.snap,
    )

    cue = cue_manager.add_memory_cue(
        position=position,
        name=body.name,
        color=body.color,
        loop_end=create_cue_position(position_ms=body.loop_end_ms, snap="beat") if body.loop_end_ms else None,
    )

    saved_cue = _persist_cues(track, [cue], mode)[0]

    return {"success": True, "cue": saved_cue.model_dump(mode="json")}


@router.post("/loop")
async def add_loop(body: AddLoopRequest) -> dict[str, Any]:
    """Add an active loop cue to a track."""
    mode = check_write_mode()

    track = _get_track_with_analysis(body.track_id)
    beat_grid = _get_domain_beat_grid(track)

    repo = get_repository()
    existing_cues = repo.get_cues(body.track_id)
    cue_manager = CueManager(body.track_id, beat_grid, existing_cues)

    if body.loop_end_ms is None:
        raise HTTPException(status_code=422, detail="loop_end_ms is required")
    position = create_cue_position(
        position_ms=body.position_ms, beat=body.beat, bar=body.bar,
        relative_to_cue_id=body.relative_to_cue_id,
        relative_offset_ms=body.relative_offset_ms,
        relative_offset_beats=body.relative_offset_beats,
        relative_offset_bars=body.relative_offset_bars, snap=body.snap,
    )
    loop_end = create_cue_position(position_ms=body.loop_end_ms, snap=body.snap)

    cue = cue_manager.add_hot_cue(
        position=position,
        kind=body.kind,
        name=body.name,
        loop_end=loop_end,
    )

    saved_cue = _persist_cues(track, [cue], mode)[0]

    return {"success": True, "cue": saved_cue.model_dump(mode="json")}


@router.put("/{cue_id}")
async def update_cue(cue_id: str, body: UpdateCueRequest) -> dict[str, Any]:
    """Update an existing cue point."""
    mode = check_write_mode()

    track = _get_track_with_analysis(body.track_id)
    beat_grid = _get_domain_beat_grid(track)

    repo = get_repository()
    existing_cues = repo.get_cues(body.track_id)
    cue_manager = CueManager(body.track_id, beat_grid, existing_cues)

    has_position_spec = any((body.position_ms is not None, body.beat is not None, body.bar is not None, body.relative_to_cue_id is not None))
    position = create_cue_position(
        position_ms=body.position_ms, beat=body.beat, bar=body.bar,
        relative_to_cue_id=body.relative_to_cue_id,
        relative_offset_ms=body.relative_offset_ms,
        relative_offset_beats=body.relative_offset_beats,
        relative_offset_bars=body.relative_offset_bars, snap=body.snap,
    ) if has_position_spec else None
    loop_end = create_cue_position(position_ms=body.loop_end_ms, snap=body.snap) if body.loop_end_ms is not None else None

    updated_cue = cue_manager.update_cue(
        cue_id=cue_id,
        position=position,
        name=body.name,
        color_table_index=body.color_table_index,
        color=body.color,
        loop_end=loop_end,
    )

    if not updated_cue:
        raise HTTPException(status_code=404, detail=f"Cue {cue_id} not found")

    if mode == OperationMode.XML:
        saved_cue = updated_cue
        _persist_xml_cues(track, [c for c in existing_cues if c.id != cue_id] + [updated_cue])
    else:
        saved_cue = repo.update_cue(cue_id, updated_cue.model_dump())

    return {"success": True, "cue": saved_cue.model_dump(mode="json") if saved_cue else None}


@router.delete("/{cue_id}")
async def delete_cue(cue_id: str, track_id: int) -> dict[str, Any]:
    """Delete a cue point."""
    mode = check_write_mode()

    repo = get_repository()
    if mode == OperationMode.XML:
        cue = repo.get_cue(cue_id)
        if not cue:
            raise HTTPException(status_code=404, detail=f"Cue {cue_id} not found")
        track = _get_track_with_analysis(cue.track_id)
        _persist_xml_cues(track, [c for c in repo.get_cues(cue.track_id) if c.id != cue_id])
        success = True
    else:
        success = repo.delete_cue(cue_id)

    if not success:
        raise HTTPException(status_code=404, detail=f"Cue {cue_id} not found")

    return {"success": success, "cue_id": cue_id}


@router.post("/{track_id}/snap")
async def snap_to_beatgrid(track_id: int, cue_id: str, grid: Literal["beat", "bar"] = "beat") -> dict[str, Any]:
    """Snap an existing cue to the beat grid."""
    mode = check_write_mode()

    track = _get_track_with_analysis(track_id)
    beat_grid = _get_domain_beat_grid(track)

    repo = get_repository()
    existing_cues = repo.get_cues(track_id)
    cue_manager = CueManager(track_id, beat_grid, existing_cues)

    snapped_cue = cue_manager.snap_cue_to_beatgrid(cue_id, grid)

    if not snapped_cue:
        raise HTTPException(status_code=404, detail=f"Cue {cue_id} not found")

    if mode == OperationMode.XML:
        saved_cue = snapped_cue
        _persist_xml_cues(track, [c if c.id != cue_id else snapped_cue for c in existing_cues])
    else:
        saved_cue = repo.update_cue(cue_id, snapped_cue.model_dump())

    return {"success": True, "cue": saved_cue.model_dump(mode="json") if saved_cue else None}


@router.post("/{track_id}/generate")
async def generate_cues(track_id: int, body: GenerateCuesRequest) -> dict[str, Any]:
    """Generate cues for a track using the configured cue strategy."""
    write_mode = check_write_mode()

    track = _get_track_with_analysis(track_id)

    strategy = get_cue_strategy()
    proposal = strategy.propose(track)

    repo = get_repository()
    existing_cues = repo.get_cues(track_id)
    beat_grid = _get_domain_beat_grid(track)
    cue_manager = CueManager(track_id, beat_grid, existing_cues)

    new_cues = cue_manager.generate_cues_from_profile(
        profile=strategy.profile,
        strategy_proposal=proposal,
        mode=body.mode,
    )

    # ``CueManager`` only updates its in-memory list for replace; remove the
    # persisted records as well before writing the generated set.
    if body.mode == "replace" and write_mode != OperationMode.XML:
        for cue in existing_cues:
            repo.delete_cue(cue.id)

    if write_mode == OperationMode.XML:
        saved_cue_models = _persist_cues(track, new_cues, write_mode)
    else:
        saved_cue_models = [repo.add_cue(track_id, cue) for cue in new_cues]
    saved_cues = [saved.model_dump(mode="json") for saved in saved_cue_models]

    return {
        "success": True,
        "track_id": track_id,
        "generated_count": len(saved_cues),
        "cues": saved_cues,
        "confidence": proposal.confidence,
        "notes": proposal.notes,
    }
