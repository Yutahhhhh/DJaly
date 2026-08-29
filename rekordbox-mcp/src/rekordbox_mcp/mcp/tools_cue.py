"""Cue management tools for Rekordbox MCP."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Literal

from fastmcp import FastMCP

from rekordbox_mcp.domain.models import (
    CueKind,
    CuePoint,
    CueType,
    HotCueColorTableIndex,
    MemoryCueColor,
    OperationMode,
)
from rekordbox_mcp.domain.beatgrid import BeatGrid as BeatGridDomain
from rekordbox_mcp.db.xml_writer import RekordboxXmlWriter
from rekordbox_mcp.domain.cue import CueManager, CuePosition, create_cue_position
from rekordbox_mcp.mcp.server import (
    get_connection,
    get_cue_strategy,
    get_mcp,
    get_repository,
    get_settings_instance,
    ensure_initial_backup_if_needed,
    require_db,
)

mcp: FastMCP = get_mcp()


def _check_write_mode() -> OperationMode:
    """Check if we're in a write mode and Rekordbox is not running."""
    settings = get_settings_instance()
    mode = settings.mode
    if mode == OperationMode.READONLY:
        raise RuntimeError("Write operations require masterdb or xml mode. Use set_mode to change mode.")
    if mode == OperationMode.MASTERDB:
        conn = get_connection()
        if conn.is_rekordbox_running():
            raise RuntimeError("Rekordbox is running. Close Rekordbox before write operations.")
    ensure_initial_backup_if_needed()
    return mode


def _persist_cues(track: Any, cues: list[CuePoint], mode: OperationMode) -> list[CuePoint]:
    """Persist cues to the selected backend and return the saved cues."""
    repo = get_repository()
    if mode == OperationMode.XML:
        path = get_settings_instance().xml_path_obj
        path.parent.mkdir(parents=True, exist_ok=True)
        writer = RekordboxXmlWriter(path)
        writer.sync_cues_for_track(track, cues)
        writer.save(path)
        return cues
    return [repo.add_cue(track.id, cue) for cue in cues]


def _persist_xml_cues(track: Any, cues: list[CuePoint]) -> None:
    path = get_settings_instance().xml_path_obj
    path.parent.mkdir(parents=True, exist_ok=True)
    writer = RekordboxXmlWriter(path)
    writer.sync_cues_for_track(track, cues)
    writer.save(path)


def _get_track_with_analysis(track_id: int) -> Any:
    """Get track with beat grid, phrases, and waveform loaded."""
    repo = get_repository()
    track = repo.get_track(track_id)
    if not track:
        raise ValueError(f"Track {track_id} not found")
    if not track.beat_grid:
        raise ValueError(f"Track {track_id} has no beat grid (BPM not analyzed)")
    return track


def _get_domain_beat_grid(track: Any) -> BeatGridDomain:
    """Convert a Track's pydantic beat grid to the domain beat grid.

    Track models expose ``models.BeatGrid`` for serialization, while
    ``CueManager`` needs the domain ``BeatGrid`` dataclass for snapping and
    timing calculations. Keep that boundary conversion in one place so all
    cue-writing tools use the same representation.
    """
    return BeatGridDomain.from_model(track.beat_grid)


@mcp.tool(
    name="get_cues",
    description="Get all cue points for a track",
    tags={"cue", "read"},
    annotations={"readOnlyHint": True},
)
@require_db
async def get_cues(track_id: int) -> dict[str, Any]:
    """Get all cue points for a track."""
    repo = get_repository()
    cues = await asyncio.to_thread(repo.get_cues, track_id)
    return {
        "track_id": track_id,
        "cues": [cue.model_dump(mode="json") for cue in cues],
        "hot_cues": [c.model_dump(mode="json") for c in cues if c.is_hot_cue],
        "memory_cues": [c.model_dump(mode="json") for c in cues if c.is_memory_cue],
        "loops": [c.model_dump(mode="json") for c in cues if c.is_loop],
    }


@mcp.tool(
    name="add_hot_cue",
    description="Add a hot cue to a track",
    tags={"cue", "write"},
    annotations={"readOnlyHint": False, "destructiveHint": False},
)
@require_db
async def add_hot_cue(
    track_id: int,
    position_ms: float | None = None,
    kind: int = 1,
    name: str = "",
    color_table_index: int | None = None,
    loop_end_ms: float | None = None,
    beat: int | None = None,
    bar: int | None = None,
    relative_to_cue_id: str | None = None,
    relative_offset_ms: float = 0.0,
    relative_offset_beats: float = 0.0,
    relative_offset_bars: float = 0.0,
    snap: Literal["none", "beat", "bar", "half_beat", "quarter_beat"] = "beat",
) -> dict[str, Any]:
    """Add a hot cue to a track."""
    mode = _check_write_mode()

    track = await asyncio.to_thread(_get_track_with_analysis, track_id)
    beat_grid = _get_domain_beat_grid(track)

    # Create cue manager
    repo = get_repository()
    existing_cues = await asyncio.to_thread(repo.get_cues, track_id)
    cue_manager = CueManager(track_id, beat_grid, existing_cues)

    # Create position
    position = create_cue_position(
        position_ms=position_ms,
        beat=beat,
        bar=bar,
        relative_to_cue_id=relative_to_cue_id,
        relative_offset_ms=relative_offset_ms,
        relative_offset_beats=relative_offset_beats,
        relative_offset_bars=relative_offset_bars,
        snap=snap,
    )

    # Add hot cue
    cue = await asyncio.to_thread(
        cue_manager.add_hot_cue,
        position=position,
        kind=kind,
        name=name,
        color_table_index=color_table_index,
        loop_end=create_cue_position(position_ms=loop_end_ms, snap="beat") if loop_end_ms else None,
    )

    # Persist to database
    repo = get_repository()
    saved_cue = (await asyncio.to_thread(_persist_cues, track, [cue], mode))[0]

    return {"success": True, "cue": saved_cue.model_dump(mode="json")}


@mcp.tool(
    name="add_memory_cue",
    description="Add a memory cue to a track",
    tags={"cue", "write"},
    annotations={"readOnlyHint": False, "destructiveHint": False},
)
@require_db
async def add_memory_cue(
    track_id: int,
    position_ms: float | None = None,
    name: str = "",
    color: int = 0,
    loop_end_ms: float | None = None,
    beat: int | None = None,
    bar: int | None = None,
    relative_to_cue_id: str | None = None,
    relative_offset_ms: float = 0.0,
    relative_offset_beats: float = 0.0,
    relative_offset_bars: float = 0.0,
    snap: Literal["none", "beat", "bar", "half_beat", "quarter_beat"] = "beat",
) -> dict[str, Any]:
    """Add a memory cue to a track."""
    mode = _check_write_mode()

    track = await asyncio.to_thread(_get_track_with_analysis, track_id)
    beat_grid = _get_domain_beat_grid(track)

    repo = get_repository()
    existing_cues = await asyncio.to_thread(repo.get_cues, track_id)
    cue_manager = CueManager(track_id, beat_grid, existing_cues)

    position = create_cue_position(
        position_ms=position_ms, beat=beat, bar=bar,
        relative_to_cue_id=relative_to_cue_id,
        relative_offset_ms=relative_offset_ms,
        relative_offset_beats=relative_offset_beats,
        relative_offset_bars=relative_offset_bars, snap=snap,
    )

    cue = await asyncio.to_thread(
        cue_manager.add_memory_cue,
        position=position,
        name=name,
        color=color,
        loop_end=create_cue_position(position_ms=loop_end_ms, snap="beat") if loop_end_ms else None,
    )

    repo = get_repository()
    saved_cue = (await asyncio.to_thread(_persist_cues, track, [cue], mode))[0]

    return {"success": True, "cue": saved_cue.model_dump(mode="json")}


@mcp.tool(
    name="add_loop",
    description="Add a loop cue (hot cue with loop end) to a track",
    tags={"cue", "write"},
    annotations={"readOnlyHint": False, "destructiveHint": False},
)
@require_db
async def add_loop(
    track_id: int,
    position_ms: float | None = None,
    loop_end_ms: float | None = None,
    kind: int = 2,
    name: str = "",
    beat: int | None = None,
    bar: int | None = None,
    relative_to_cue_id: str | None = None,
    relative_offset_ms: float = 0.0,
    relative_offset_beats: float = 0.0,
    relative_offset_bars: float = 0.0,
    snap: Literal["none", "beat", "bar", "half_beat", "quarter_beat"] = "beat",
) -> dict[str, Any]:
    """Add a loop cue to a track."""
    mode = _check_write_mode()

    track = await asyncio.to_thread(_get_track_with_analysis, track_id)
    beat_grid = _get_domain_beat_grid(track)

    repo = get_repository()
    existing_cues = await asyncio.to_thread(repo.get_cues, track_id)
    cue_manager = CueManager(track_id, beat_grid, existing_cues)

    if loop_end_ms is None:
        raise ValueError("loop_end_ms is required")
    position = create_cue_position(
        position_ms=position_ms, beat=beat, bar=bar,
        relative_to_cue_id=relative_to_cue_id,
        relative_offset_ms=relative_offset_ms,
        relative_offset_beats=relative_offset_beats,
        relative_offset_bars=relative_offset_bars, snap=snap,
    )
    loop_end = create_cue_position(position_ms=loop_end_ms, snap=snap)

    cue = await asyncio.to_thread(
        cue_manager.add_hot_cue,
        position=position,
        kind=kind,
        name=name,
        loop_end=loop_end,
    )

    repo = get_repository()
    saved_cue = (await asyncio.to_thread(_persist_cues, track, [cue], mode))[0]

    return {"success": True, "cue": saved_cue.model_dump(mode="json")}


@mcp.tool(
    name="update_cue",
    description="Update an existing cue point",
    tags={"cue", "write"},
    annotations={"readOnlyHint": False, "destructiveHint": False},
)
@require_db
async def update_cue(
    cue_id: str,
    track_id: int | None = None,
    position_ms: float | None = None,
    name: str | None = None,
    color_table_index: int | None = None,
    color: int | None = None,
    loop_end_ms: float | None = None,
    beat: int | None = None,
    bar: int | None = None,
    relative_to_cue_id: str | None = None,
    relative_offset_ms: float = 0.0,
    relative_offset_beats: float = 0.0,
    relative_offset_bars: float = 0.0,
    snap: Literal["none", "beat", "bar", "half_beat", "quarter_beat"] = "beat",
) -> dict[str, Any]:
    """Update an existing cue point."""
    mode = _check_write_mode()

    repo = get_repository()

    cue = await asyncio.to_thread(repo.get_cue, cue_id)
    if not cue:
        return {"success": False, "error": f"Cue {cue_id} not found"}
    resolved_track_id = track_id if track_id is not None else cue.track_id

    track = await asyncio.to_thread(_get_track_with_analysis, resolved_track_id)
    beat_grid = _get_domain_beat_grid(track)

    existing_cues = await asyncio.to_thread(repo.get_cues, resolved_track_id)
    cue_manager = CueManager(resolved_track_id, beat_grid, existing_cues)

    has_position_spec = any((position_ms is not None, beat is not None, bar is not None, relative_to_cue_id is not None))
    position = create_cue_position(
        position_ms=position_ms, beat=beat, bar=bar,
        relative_to_cue_id=relative_to_cue_id,
        relative_offset_ms=relative_offset_ms,
        relative_offset_beats=relative_offset_beats,
        relative_offset_bars=relative_offset_bars, snap=snap,
    ) if has_position_spec else None
    loop_end = create_cue_position(position_ms=loop_end_ms, snap=snap) if loop_end_ms is not None else None

    updated_cue = await asyncio.to_thread(
        cue_manager.update_cue,
        cue_id=cue_id,
        position=position,
        name=name,
        color_table_index=color_table_index,
        color=color,
        loop_end=loop_end,
    )

    if not updated_cue:
        return {"success": False, "error": f"Cue {cue_id} not found"}

    # Persist to database
    if mode == OperationMode.XML:
        saved_cue = updated_cue
        await asyncio.to_thread(_persist_xml_cues, track, [c for c in existing_cues if c.id != cue_id] + [updated_cue])
    else:
        saved_cue = await asyncio.to_thread(repo.update_cue, cue_id, updated_cue.model_dump())

    return {"success": True, "cue": saved_cue.model_dump(mode="json") if saved_cue else None}


@mcp.tool(
    name="delete_cue",
    description="Delete a cue point",
    tags={"cue", "write"},
    annotations={"readOnlyHint": False, "destructiveHint": True},
)
@require_db
async def delete_cue(cue_id: str, track_id: int | None = None) -> dict[str, Any]:
    """Delete a cue point."""
    mode = _check_write_mode()

    repo = get_repository()
    if mode == OperationMode.XML:
        cue = await asyncio.to_thread(repo.get_cue, cue_id)
        if not cue:
            return {"success": False, "cue_id": cue_id}
        track = await asyncio.to_thread(_get_track_with_analysis, cue.track_id)
        cues = [c for c in await asyncio.to_thread(repo.get_cues, cue.track_id) if c.id != cue_id]
        await asyncio.to_thread(_persist_xml_cues, track, cues)
        success = True
    else:
        success = await asyncio.to_thread(repo.delete_cue, cue_id)

    return {"success": success, "cue_id": cue_id}


@mcp.tool(
    name="snap_to_beatgrid",
    description="Snap a cue to the beat grid",
    tags={"cue", "write"},
    annotations={"readOnlyHint": False, "destructiveHint": False},
)
@require_db
async def snap_to_beatgrid(track_id: int, cue_id: str, grid: Literal["beat", "bar"] = "beat") -> dict[str, Any]:
    """Snap an existing cue to the beat grid."""
    mode = _check_write_mode()

    track = await asyncio.to_thread(_get_track_with_analysis, track_id)
    beat_grid = _get_domain_beat_grid(track)

    repo = get_repository()
    existing_cues = await asyncio.to_thread(repo.get_cues, track_id)
    cue_manager = CueManager(track_id, beat_grid, existing_cues)

    snapped_cue = await asyncio.to_thread(cue_manager.snap_cue_to_beatgrid, cue_id, grid)

    if not snapped_cue:
        return {"success": False, "error": f"Cue {cue_id} not found"}

    # Persist
    if mode == OperationMode.XML:
        saved_cue = snapped_cue
        await asyncio.to_thread(_persist_xml_cues, track, [c if c.id != cue_id else snapped_cue for c in existing_cues])
    else:
        saved_cue = await asyncio.to_thread(repo.update_cue, cue_id, snapped_cue.model_dump())

    return {"success": True, "cue": saved_cue.model_dump(mode="json") if saved_cue else None}


@mcp.tool(
    name="generate_cues",
    description="Generate cues for a track using the cue strategy",
    tags={"cue", "write"},
    annotations={"readOnlyHint": False, "destructiveHint": False},
)
@require_db
async def generate_cues(
    track_id: int,
    profile: str = "default",
    mode: Literal["replace", "merge", "preserve"] = "replace",
) -> dict[str, Any]:
    """Generate cues for a track using the configured cue strategy."""
    write_mode = _check_write_mode()

    track = await asyncio.to_thread(_get_track_with_analysis, track_id)

    # Get cue strategy
    strategy = get_cue_strategy()
    if profile != "default":
        from rekordbox_mcp.domain.strategy import create_cue_strategy
        settings = get_settings_instance()
        strategy = create_cue_strategy(
            profile_name=profile,
            memory_offset_bars=settings.cue_memory_offset_bars,
            loop_length_bars=settings.cue_loop_length_bars,
        )

    # Generate proposal
    proposal = await asyncio.to_thread(strategy.propose, track)

    # Get existing cues
    repo = get_repository()
    existing_cues = await asyncio.to_thread(repo.get_cues, track_id)
    beat_grid = _get_domain_beat_grid(track)
    cue_manager = CueManager(track_id, beat_grid, existing_cues)

    # Generate cues from proposal
    new_cues = await asyncio.to_thread(
        cue_manager.generate_cues_from_profile,
        profile=strategy.profile,
        strategy_proposal=proposal,
        mode=mode,
    )

    # ``CueManager`` only builds the replacement set; remove persisted cues here
    # before adding the newly generated ones.
    if mode == "replace":
        for cue in existing_cues:
            await asyncio.to_thread(repo.delete_cue, cue.id)

    # Persist all new cues
    saved_cues = []
    if write_mode == OperationMode.XML:
        saved_cue_models = await asyncio.to_thread(_persist_cues, track, new_cues, write_mode)
    else:
        saved_cue_models = [await asyncio.to_thread(repo.add_cue, track_id, cue) for cue in new_cues]
    for saved in saved_cue_models:
        saved_cues.append(saved.model_dump(mode="json"))

    return {
        "success": True,
        "track_id": track_id,
        "generated_count": len(saved_cues),
        "cues": saved_cues,
        "confidence": proposal.confidence,
        "notes": proposal.notes,
    }


@mcp.tool(
    name="get_cue_profiles",
    description="Get available cue profiles",
    tags={"cue", "read"},
    annotations={"readOnlyHint": True},
)
async def get_cue_profiles() -> dict[str, Any]:
    """Get available cue profiles."""
    from rekordbox_mcp.domain.models import CueProfile
    profiles = [CueProfile.default()]
    directories = {Path("~/.rekordbox-mcp/profiles").expanduser()}
    configured = get_settings_instance().cue_profile
    configured_path = Path(configured).expanduser()
    if configured_path.suffix.lower() == ".csv":
        directories.add(configured_path.parent)
    elif configured_path.is_dir():
        directories.add(configured_path)
    seen = {profiles[0].name}
    for directory in directories:
        if not directory.is_dir():
            continue
        for path in sorted(directory.glob("*.csv")):
            try:
                profile = CueProfile.from_csv(path)
            except (OSError, ValueError):
                continue
            from rekordbox_mcp.domain.strategy import register_cue_profile
            register_cue_profile(profile)
            if profile.name not in seen:
                profiles.append(profile)
                seen.add(profile.name)
    return {
        "profiles": [profile.model_dump(mode="json") for profile in profiles],
        "current": get_settings_instance().cue_profile,
    }


@mcp.tool(
    name="set_cue_profile",
    description="Set the active cue profile",
    tags={"cue", "write"},
    annotations={"readOnlyHint": False, "destructiveHint": False},
)
async def set_cue_profile(profile_name: str) -> dict[str, Any]:
    """Set the active cue profile."""
    settings = get_settings_instance()

    # Recreate cue strategy with new profile
    from rekordbox_mcp.domain.strategy import create_cue_strategy
    from rekordbox_mcp.mcp.server import set_service

    cue_strategy = create_cue_strategy(
        profile_name=profile_name,
        memory_offset_bars=settings.cue_memory_offset_bars,
        loop_length_bars=settings.cue_loop_length_bars,
    )
    set_service("cue_strategy", cue_strategy)
    settings.cue_profile = profile_name

    return {"success": True, "profile": profile_name}
