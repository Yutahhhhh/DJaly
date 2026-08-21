"""Cue domain logic - CRUD operations, relative positioning, snapping."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from rekordbox_mcp.domain.models import (
    BeatGrid,
    CuePoint,
    CueProfile,
    CueSlotConfig,
    CueType,
    HotCueColorTableIndex,
    MemoryCueColor,
)
from rekordbox_mcp.domain.beatgrid import BeatGrid as BeatGridDomain


@dataclass
class CuePosition:
    """Represents a cue position with various reference options."""

    position_ms: float
    beat: int | None = None
    bar: int | None = None
    relative_to_cue_id: str | None = None
    relative_offset_ms: float = 0.0
    relative_offset_beats: float = 0.0
    relative_offset_bars: float = 0.0
    snap: Literal["none", "beat", "bar", "half_beat", "quarter_beat"] = "beat"


class CueManager:
    """Manages cue operations for a track."""

    def __init__(self, track_id: int, beat_grid: BeatGridDomain, existing_cues: list[CuePoint]):
        self.track_id = track_id
        self.beat_grid = beat_grid
        self.existing_cues = {c.id: c for c in existing_cues}

    def resolve_position(self, pos: CuePosition) -> float:
        """Resolve a CuePosition to absolute milliseconds."""
        # Start with explicit position
        ms = pos.position_ms

        # Apply relative offset from another cue
        if pos.relative_to_cue_id and pos.relative_to_cue_id in self.existing_cues:
            ref_cue = self.existing_cues[pos.relative_to_cue_id]
            ms = ref_cue.position_ms + pos.relative_offset_ms
            ms += pos.relative_offset_beats * self.beat_grid.ms_per_beat
            ms += pos.relative_offset_bars * self.beat_grid.ms_per_bar

        # Apply beat/bar positioning
        if pos.beat is not None:
            ms = self.beat_grid.beat_to_ms(pos.beat)
        elif pos.bar is not None:
            ms = self.beat_grid.get_bar_start_ms(pos.bar)

        # Apply snapping
        if pos.snap != "none":
            ms = self.beat_grid.snap_to_grid(ms, pos.snap)

        return max(0, ms)

    def add_hot_cue(
        self,
        position: CuePosition,
        kind: CueType | int,
        name: str = "",
        color_table_index: int | None = None,
        color: int = -1,
        loop_end: CuePosition | None = None,
    ) -> CuePoint:
        """Add a hot cue."""
        kind_int = kind.value if isinstance(kind, CueType) else kind
        if not (1 <= kind_int <= 9):
            raise ValueError("Hot cue kind must be 1-9")

        pos_ms = self.resolve_position(position)

        loop_end_ms = None
        if loop_end:
            loop_end_ms = self.resolve_position(loop_end)

        # Determine color
        if color_table_index is None:
            # Auto-assign based on kind
            color_map = {
                1: HotCueColorTableIndex.GREEN,
                2: HotCueColorTableIndex.GREEN,
                3: HotCueColorTableIndex.YELLOW,
                4: HotCueColorTableIndex.RED,
                5: HotCueColorTableIndex.RED,
                6: HotCueColorTableIndex.BLUE,
                7: HotCueColorTableIndex.PURPLE,
                8: HotCueColorTableIndex.CYAN,
                9: HotCueColorTableIndex.WHITE,
            }
            color_table_index = color_map.get(kind_int, HotCueColorTableIndex.WHITE)

        cue = CuePoint(
            track_id=self.track_id,
            kind=kind_int,
            position_ms=pos_ms,
            loop_end_ms=loop_end_ms,
            color_table_index=color_table_index,
            color=color,
            comment=name,
        )
        return cue

    def add_memory_cue(
        self,
        position: CuePosition,
        name: str = "",
        color: MemoryCueColor | int = MemoryCueColor.NONE,
        color_table_index: int | None = None,
        loop_end: CuePosition | None = None,
    ) -> CuePoint:
        """Add a memory cue."""
        pos_ms = self.resolve_position(position)

        loop_end_ms = None
        if loop_end:
            loop_end_ms = self.resolve_position(loop_end)

        color_int = color.value if isinstance(color, MemoryCueColor) else color

        cue = CuePoint(
            track_id=self.track_id,
            kind=0,  # Memory cue
            position_ms=pos_ms,
            loop_end_ms=loop_end_ms,
            color_table_index=color_table_index,
            color=color_int,
            comment=name,
        )
        return cue

    def update_cue(
        self,
        cue_id: str,
        position: CuePosition | None = None,
        name: str | None = None,
        color_table_index: int | None = None,
        color: int | None = None,
        loop_end: CuePosition | None = None,
    ) -> CuePoint | None:
        """Update an existing cue."""
        if cue_id not in self.existing_cues:
            return None

        cue = self.existing_cues[cue_id]

        if position is not None:
            cue.position_ms = self.resolve_position(position)

        if name is not None:
            cue.comment = name

        if color_table_index is not None:
            cue.color_table_index = color_table_index

        if color is not None:
            cue.color = color

        if loop_end is not None:
            cue.loop_end_ms = self.resolve_position(loop_end)
        elif loop_end is not None and loop_end.position_ms == 0:
            # Explicitly remove loop
            cue.loop_end_ms = None

        cue.updated_at = __import__("datetime").datetime.now()
        return cue

    def delete_cue(self, cue_id: str) -> bool:
        """Delete a cue."""
        if cue_id in self.existing_cues:
            del self.existing_cues[cue_id]
            return True
        return False

    def get_cue(self, cue_id: str) -> CuePoint | None:
        """Get a cue by ID."""
        return self.existing_cues.get(cue_id)

    def get_all_cues(self) -> list[CuePoint]:
        """Get all cues."""
        return list(self.existing_cues.values())

    def get_hot_cues(self) -> list[CuePoint]:
        """Get all hot cues."""
        return [c for c in self.existing_cues.values() if c.is_hot_cue]

    def get_memory_cues(self) -> list[CuePoint]:
        """Get all memory cues."""
        return [c for c in self.existing_cues.values() if c.is_memory_cue]

    def get_loops(self) -> list[CuePoint]:
        """Get all loops."""
        return [c for c in self.existing_cues.values() if c.is_loop]

    def snap_cue_to_beatgrid(self, cue_id: str, grid: Literal["beat", "bar"] = "beat") -> CuePoint | None:
        """Snap an existing cue to the beat grid."""
        cue = self.existing_cues.get(cue_id)
        if not cue:
            return None

        if grid == "beat":
            cue.position_ms = self.beat_grid.snap_to_beat(cue.position_ms)
        elif grid == "bar":
            cue.position_ms = self.beat_grid.snap_to_bar(cue.position_ms)

        if cue.loop_end_ms:
            if grid == "beat":
                cue.loop_end_ms = self.beat_grid.snap_to_beat(cue.loop_end_ms)
            elif grid == "bar":
                cue.loop_end_ms = self.beat_grid.snap_to_bar(cue.loop_end_ms)

        cue.updated_at = __import__("datetime").datetime.now()
        return cue

    def generate_cues_from_profile(
        self,
        profile: CueProfile,
        strategy_proposal: "CueProposal",
        mode: Literal["replace", "merge", "preserve"] = "replace",
    ) -> list[CuePoint]:
        """
        Generate cues from a strategy proposal according to the profile.

        Args:
            profile: Cue profile to use
            strategy_proposal: Proposed cues from strategy
            mode: How to handle existing cues
                - replace: Remove all existing cues of same type, add new
                - merge: Update existing cues at same positions, add new
                - preserve: Keep existing cues, only add new ones

        Returns:
            List of cues to apply
        """
        new_cues: list[CuePoint] = []

        if mode == "replace":
            # Remove all existing hot and memory cues
            self.existing_cues.clear()
        elif mode == "preserve":
            # Keep existing, only add if slot is empty
            existing_hot_kinds = {c.kind for c in self.get_hot_cues()}
            existing_mem_positions = {round(c.position_ms) for c in self.get_memory_cues()}

        # Add hot cues from proposal
        for proposed in strategy_proposal.hot_cues:
            if mode == "preserve" and proposed.kind in existing_hot_kinds:
                continue
            new_cues.append(proposed)

        # Add memory cues from proposal
        for proposed in strategy_proposal.memory_cues:
            if mode == "preserve" and round(proposed.position_ms) in existing_mem_positions:
                continue
            new_cues.append(proposed)

        return new_cues


def create_cue_position(
    position_ms: float | None = None,
    beat: int | None = None,
    bar: int | None = None,
    relative_to_cue_id: str | None = None,
    relative_offset_ms: float = 0.0,
    relative_offset_beats: float = 0.0,
    relative_offset_bars: float = 0.0,
    snap: Literal["none", "beat", "bar", "half_beat", "quarter_beat"] = "beat",
) -> CuePosition:
    """Factory function to create a CuePosition."""
    return CuePosition(
        position_ms=position_ms or 0.0,
        beat=beat,
        bar=bar,
        relative_to_cue_id=relative_to_cue_id,
        relative_offset_ms=relative_offset_ms,
        relative_offset_beats=relative_offset_beats,
        relative_offset_bars=relative_offset_bars,
        snap=snap,
    )


def validate_cue_slot(kind: int, is_hot_cue: bool) -> bool:
    """Validate that a cue kind is valid for the cue type."""
    if is_hot_cue:
        return 1 <= kind <= 9
    return kind == 0


def get_next_available_hot_cue_slot(existing_cues: list[CuePoint]) -> int | None:
    """Get the next available hot cue slot (1-9)."""
    used = {c.kind for c in existing_cues if c.is_hot_cue}
    for i in range(1, 10):
        if i not in used:
            return i
    return None


def get_cue_color_for_kind(kind: int) -> tuple[int, int]:
    """Get default color table index and color for a cue kind."""
    color_map = {
        1: (HotCueColorTableIndex.GREEN, MemoryCueColor.GREEN),
        2: (HotCueColorTableIndex.GREEN, MemoryCueColor.GREEN),
        3: (HotCueColorTableIndex.YELLOW, MemoryCueColor.YELLOW),
        4: (HotCueColorTableIndex.RED, MemoryCueColor.RED),
        5: (HotCueColorTableIndex.RED, MemoryCueColor.RED),
        6: (HotCueColorTableIndex.BLUE, MemoryCueColor.BLUE),
        7: (HotCueColorTableIndex.PURPLE, MemoryCueColor.PURPLE),
        8: (HotCueColorTableIndex.CYAN, MemoryCueColor.CYAN),
        9: (HotCueColorTableIndex.WHITE, MemoryCueColor.NONE),
    }
    return color_map.get(kind, (HotCueColorTableIndex.WHITE, MemoryCueColor.NONE))
