"""Tests for Cue domain logic (CueManager, CuePosition)."""

from __future__ import annotations

import pytest

from rekordbox_mcp.domain.beatgrid import BeatGrid
from rekordbox_mcp.domain.cue import (
    CueManager,
    CuePosition,
    create_cue_position,
    get_cue_color_for_kind,
    get_next_available_hot_cue_slot,
    validate_cue_slot,
)
from rekordbox_mcp.domain.models import CuePoint, CueType, MemoryCueColor


@pytest.fixture
def cue_manager(sample_beatgrid: BeatGrid) -> CueManager:
    return CueManager(track_id=1, beat_grid=sample_beatgrid, existing_cues=[])


def test_add_hot_cue_basic(cue_manager: CueManager):
    position = create_cue_position(position_ms=1000.0, snap="none")
    cue = cue_manager.add_hot_cue(position=position, kind=1, name="Drop")

    assert cue.track_id == 1
    assert cue.kind == 1
    assert cue.is_hot_cue
    assert cue.comment == "Drop"
    assert cue.position_ms == pytest.approx(1000.0)


def test_add_hot_cue_invalid_kind_raises(cue_manager: CueManager):
    position = create_cue_position(position_ms=1000.0, snap="none")
    with pytest.raises(ValueError):
        cue_manager.add_hot_cue(position=position, kind=0)
    with pytest.raises(ValueError):
        cue_manager.add_hot_cue(position=position, kind=10)


def test_add_hot_cue_auto_assigns_color(cue_manager: CueManager):
    position = create_cue_position(position_ms=1000.0, snap="none")
    cue = cue_manager.add_hot_cue(position=position, kind=1)
    assert cue.color_table_index is not None


def test_add_memory_cue_basic(cue_manager: CueManager):
    position = create_cue_position(position_ms=2000.0, snap="none")
    cue = cue_manager.add_memory_cue(position=position, name="Buildup", color=MemoryCueColor.YELLOW)

    assert cue.kind == 0
    assert cue.is_memory_cue
    assert cue.comment == "Buildup"
    assert cue.color == MemoryCueColor.YELLOW.value
    assert cue.position_ms == pytest.approx(2000.0)


def test_add_loop_sets_loop_end(cue_manager: CueManager):
    position = create_cue_position(position_ms=1000.0, snap="none")
    loop_end = create_cue_position(position_ms=3000.0, snap="none")
    cue = cue_manager.add_hot_cue(position=position, kind=2, name="Loop", loop_end=loop_end)

    assert cue.is_loop
    assert cue.loop_end_ms == pytest.approx(3000.0)


def test_update_cue_position_and_name(sample_beatgrid: BeatGrid):
    existing = CuePoint(id="c1", track_id=1, kind=1, position_ms=1000.0, comment="Old")
    manager = CueManager(track_id=1, beat_grid=sample_beatgrid, existing_cues=[existing])

    new_position = create_cue_position(position_ms=5000.0, snap="none")
    updated = manager.update_cue(cue_id="c1", position=new_position, name="New")

    assert updated is not None
    assert updated.position_ms == pytest.approx(5000.0)
    assert updated.comment == "New"


def test_update_cue_unknown_id_returns_none(cue_manager: CueManager):
    result = cue_manager.update_cue(cue_id="does-not-exist", name="X")
    assert result is None


def test_delete_cue(sample_beatgrid: BeatGrid):
    existing = CuePoint(id="c1", track_id=1, kind=1, position_ms=1000.0)
    manager = CueManager(track_id=1, beat_grid=sample_beatgrid, existing_cues=[existing])

    assert manager.delete_cue("c1") is True
    assert manager.get_cue("c1") is None
    assert manager.delete_cue("c1") is False


def test_relative_position_offset_ms(sample_beatgrid: BeatGrid):
    ref = CuePoint(id="ref", track_id=1, kind=1, position_ms=1000.0)
    manager = CueManager(track_id=1, beat_grid=sample_beatgrid, existing_cues=[ref])

    position = create_cue_position(
        relative_to_cue_id="ref", relative_offset_ms=500.0, snap="none"
    )
    resolved_ms = manager.resolve_position(position)
    assert resolved_ms == pytest.approx(1500.0)


def test_relative_position_offset_beats_and_bars(sample_beatgrid: BeatGrid):
    ref = CuePoint(id="ref", track_id=1, kind=1, position_ms=1000.0)
    manager = CueManager(track_id=1, beat_grid=sample_beatgrid, existing_cues=[ref])

    position_beats = create_cue_position(
        relative_to_cue_id="ref", relative_offset_beats=1, snap="none"
    )
    expected_beats = 1000.0 + sample_beatgrid.ms_per_beat
    assert manager.resolve_position(position_beats) == pytest.approx(expected_beats)

    position_bars = create_cue_position(
        relative_to_cue_id="ref", relative_offset_bars=1, snap="none"
    )
    expected_bars = 1000.0 + sample_beatgrid.ms_per_bar
    assert manager.resolve_position(position_bars) == pytest.approx(expected_bars)


def test_relative_position_unknown_ref_falls_back_to_position_ms(sample_beatgrid: BeatGrid):
    manager = CueManager(track_id=1, beat_grid=sample_beatgrid, existing_cues=[])
    position = create_cue_position(
        position_ms=750.0, relative_to_cue_id="missing", relative_offset_ms=500.0, snap="none"
    )
    # Since the ref cue doesn't exist, offset is ignored and position_ms is used directly.
    assert manager.resolve_position(position) == pytest.approx(750.0)


def test_beat_positioning_overrides_position_ms(cue_manager: CueManager, sample_beatgrid: BeatGrid):
    position = create_cue_position(position_ms=0.0, beat=5, snap="none")
    resolved = cue_manager.resolve_position(position)
    assert resolved == pytest.approx(sample_beatgrid.beat_to_ms(5))


def test_bar_positioning_overrides_position_ms(cue_manager: CueManager, sample_beatgrid: BeatGrid):
    position = create_cue_position(position_ms=0.0, bar=3, snap="none")
    resolved = cue_manager.resolve_position(position)
    assert resolved == pytest.approx(sample_beatgrid.get_bar_start_ms(3))


def test_snap_beat_and_bar(cue_manager: CueManager, sample_beatgrid: BeatGrid):
    off_grid_ms = sample_beatgrid.first_beat_ms + 10.0

    beat_snapped = create_cue_position(position_ms=off_grid_ms, snap="beat")
    assert cue_manager.resolve_position(beat_snapped) == pytest.approx(
        sample_beatgrid.snap_to_beat(off_grid_ms)
    )

    bar_snapped = create_cue_position(position_ms=off_grid_ms, snap="bar")
    assert cue_manager.resolve_position(bar_snapped) == pytest.approx(
        sample_beatgrid.snap_to_bar(off_grid_ms)
    )


def test_resolve_position_never_negative(cue_manager: CueManager):
    position = create_cue_position(position_ms=-500.0, snap="none")
    assert cue_manager.resolve_position(position) == 0


def test_snap_cue_to_beatgrid(sample_beatgrid: BeatGrid):
    off_grid_ms = sample_beatgrid.first_beat_ms + 10.0
    existing = CuePoint(id="c1", track_id=1, kind=1, position_ms=off_grid_ms)
    manager = CueManager(track_id=1, beat_grid=sample_beatgrid, existing_cues=[existing])

    snapped = manager.snap_cue_to_beatgrid("c1", grid="beat")
    assert snapped is not None
    assert snapped.position_ms == pytest.approx(sample_beatgrid.snap_to_beat(off_grid_ms))


def test_get_hot_memory_and_loop_cues(sample_beatgrid: BeatGrid):
    hot = CuePoint(id="h1", track_id=1, kind=1, position_ms=100.0)
    memory = CuePoint(id="m1", track_id=1, kind=0, position_ms=200.0)
    loop = CuePoint(id="l1", track_id=1, kind=2, position_ms=300.0, loop_end_ms=500.0)
    manager = CueManager(track_id=1, beat_grid=sample_beatgrid, existing_cues=[hot, memory, loop])

    assert [c.id for c in manager.get_hot_cues()] == ["h1", "l1"]
    assert [c.id for c in manager.get_memory_cues()] == ["m1"]
    assert [c.id for c in manager.get_loops()] == ["l1"]
    assert len(manager.get_all_cues()) == 3


def test_validate_cue_slot():
    assert validate_cue_slot(1, is_hot_cue=True) is True
    assert validate_cue_slot(0, is_hot_cue=True) is False
    assert validate_cue_slot(0, is_hot_cue=False) is True
    assert validate_cue_slot(1, is_hot_cue=False) is False


def test_get_next_available_hot_cue_slot():
    cues = [CuePoint(track_id=1, kind=k, position_ms=0.0) for k in (1, 2, 3)]
    assert get_next_available_hot_cue_slot(cues) == 4
    assert get_next_available_hot_cue_slot([]) == 1


def test_get_next_available_hot_cue_slot_all_used():
    cues = [CuePoint(track_id=1, kind=k, position_ms=0.0) for k in range(1, 10)]
    assert get_next_available_hot_cue_slot(cues) is None


def test_get_cue_color_for_kind_known_and_unknown():
    color_table, mem_color = get_cue_color_for_kind(1)
    assert color_table is not None
    unknown_table, unknown_mem = get_cue_color_for_kind(999)
    assert unknown_mem == MemoryCueColor.NONE
