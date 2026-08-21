"""Beat Grid domain logic for beat/bar snapping and conversion."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from rekordbox_mcp.domain.models import BeatGrid as BeatGridModel


@dataclass(frozen=True)
class BeatGrid:
    """Immutable beat grid for timing calculations."""

    first_beat_ms: float
    bpm: float

    @property
    def ms_per_beat(self) -> float:
        return 60_000.0 / self.bpm

    @property
    def ms_per_bar(self) -> float:
        return self.ms_per_beat * 4

    def beat_to_ms(self, beat: int) -> float:
        """Convert 1-indexed beat number to milliseconds."""
        if beat < 1:
            beat = 1
        return self.first_beat_ms + (beat - 1) * self.ms_per_beat

    def ms_to_beat(self, ms: float) -> int:
        """Convert milliseconds to nearest 1-indexed beat number."""
        raw = (ms - self.first_beat_ms) / self.ms_per_beat + 1
        return max(1, round(raw))

    def ms_to_beat_exact(self, ms: float) -> float:
        """Convert milliseconds to exact beat position (float)."""
        return (ms - self.first_beat_ms) / self.ms_per_beat + 1

    def bars_to_ms(self, bars: int) -> float:
        """Convert number of bars to milliseconds."""
        return bars * self.ms_per_bar

    def ms_to_bar(self, ms: float) -> int:
        """Convert milliseconds to 1-indexed bar number."""
        beat = self.ms_to_beat(ms)
        return ((beat - 1) // 4) + 1

    def snap_to_beat(self, ms: float) -> float:
        """Snap milliseconds to nearest beat."""
        beat = self.ms_to_beat(ms)
        return self.beat_to_ms(beat)

    def snap_to_bar(self, ms: float) -> float:
        """Snap milliseconds to nearest bar (downbeat)."""
        beat = self.ms_to_beat(ms)
        bar_beat = ((beat - 1) // 4) * 4 + 1
        return self.beat_to_ms(bar_beat)

    def snap_to_grid(
        self, ms: float, grid: Literal["beat", "bar", "half_beat", "quarter_beat"] = "beat"
    ) -> float:
        """Snap to specified grid division."""
        if grid == "beat":
            return self.snap_to_beat(ms)
        elif grid == "bar":
            return self.snap_to_bar(ms)
        elif grid == "half_beat":
            # Snap to nearest half beat
            exact_beat = self.ms_to_beat_exact(ms)
            half_beat = round(exact_beat * 2) / 2
            return self.first_beat_ms + (half_beat - 1) * self.ms_per_beat
        elif grid == "quarter_beat":
            # Snap to nearest quarter beat
            exact_beat = self.ms_to_beat_exact(ms)
            quarter_beat = round(exact_beat * 4) / 4
            return self.first_beat_ms + (quarter_beat - 1) * self.ms_per_beat
        else:
            return self.snap_to_beat(ms)

    def get_bar_start_ms(self, bar: int) -> float:
        """Get millisecond position of bar start (1-indexed)."""
        if bar < 1:
            bar = 1
        beat = (bar - 1) * 4 + 1
        return self.beat_to_ms(beat)

    def get_beat_position(self, ms: float) -> dict[str, int | float]:
        """Get detailed beat position info for a timestamp."""
        exact_beat = self.ms_to_beat_exact(ms)
        beat = max(1, round(exact_beat))
        bar = ((beat - 1) // 4) + 1
        beat_in_bar = ((beat - 1) % 4) + 1
        return {
            "exact_beat": exact_beat,
            "beat": beat,
            "bar": bar,
            "beat_in_bar": beat_in_bar,
            "ms": ms,
            "snapped_beat_ms": self.snap_to_beat(ms),
            "snapped_bar_ms": self.snap_to_bar(ms),
        }

    @classmethod
    def from_model(cls, model: BeatGridModel) -> BeatGrid:
        return cls(first_beat_ms=model.first_beat_ms, bpm=model.bpm)

    def to_model(self) -> BeatGridModel:
        return BeatGridModel(first_beat_ms=self.first_beat_ms, bpm=self.bpm)


def create_beat_grid_from_analysis(
    first_beat_ms: float, bpm_times_100: int
) -> BeatGrid:
    """Create BeatGrid from rekordbox analysis values (BPM stored as *100)."""
    bpm = bpm_times_100 / 100.0
    return BeatGrid(first_beat_ms=first_beat_ms, bpm=bpm)


def estimate_beat_grid_from_bpm(bpm: float, first_beat_ms: float = 0.0) -> BeatGrid:
    """Estimate beat grid from BPM alone (first_beat_ms defaults to 0)."""
    return BeatGrid(first_beat_ms=first_beat_ms, bpm=bpm)