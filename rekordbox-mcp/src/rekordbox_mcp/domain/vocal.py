"""PVDI Vocal detection domain logic."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass
class VocalRegion:
    """A detected vocal region."""

    start_frame: int
    end_frame: int
    start_ms: float
    end_ms: float
    duration_ms: float
    avg_confidence: float
    max_confidence: int


@dataclass
class VocalAnalysisResult:
    """Result of PVDI vocal analysis."""

    vocal_track: list[int]  # Per-frame confidence (0-4)
    frame_ms: float  # Milliseconds per frame (~46.4ms)
    regions: list[VocalRegion]
    total_vocal_frames: int
    total_frames: int
    vocal_ratio: float


# PVDI frame rate: 22050 Hz sample rate, 1024 samples per frame
# Frame duration = 1024 / 22050 * 1000 ≈ 46.44 ms
PVDI_FRAME_MS = 1024 / 22050 * 1000  # ~46.44ms


def analyze_vocal_track(
    vocal_track: list[int],
    min_confidence: int = 3,
    min_duration_ms: float = 2000.0,
) -> VocalAnalysisResult:
    """
    Analyze PVDI vocal track data to find vocal regions.

    Args:
        vocal_track: List of per-frame vocal confidence values (0-4)
        min_confidence: Minimum confidence threshold (0-4) for vocal detection
        min_duration_ms: Minimum duration in ms for a valid vocal region

    Returns:
        VocalAnalysisResult with detected vocal regions
    """
    if not vocal_track:
        return VocalAnalysisResult(
            vocal_track=[],
            frame_ms=PVDI_FRAME_MS,
            regions=[],
            total_vocal_frames=0,
            total_frames=0,
            vocal_ratio=0.0,
        )

    total_frames = len(vocal_track)
    vocal_frames = sum(1 for v in vocal_track if v > 0)
    vocal_ratio = vocal_frames / total_frames if total_frames > 0 else 0.0

    regions: list[VocalRegion] = []
    min_frames = int(min_duration_ms / PVDI_FRAME_MS)

    i = 0
    while i < total_frames:
        if vocal_track[i] >= min_confidence:
            start = i
            max_conf = vocal_track[i]
            while i < total_frames and vocal_track[i] > 0:
                max_conf = max(max_conf, vocal_track[i])
                i += 1
            end = i

            if end - start >= min_frames:
                start_ms = start * PVDI_FRAME_MS
                end_ms = end * PVDI_FRAME_MS
                duration_ms = end_ms - start_ms
                avg_conf = sum(vocal_track[start:end]) / (end - start)

                regions.append(
                    VocalRegion(
                        start_frame=start,
                        end_frame=end,
                        start_ms=start_ms,
                        end_ms=end_ms,
                        duration_ms=duration_ms,
                        avg_confidence=avg_conf,
                        max_confidence=max_conf,
                    )
                )
        else:
            i += 1

    return VocalAnalysisResult(
        vocal_track=vocal_track,
        frame_ms=PVDI_FRAME_MS,
        regions=regions,
        total_vocal_frames=vocal_frames,
        total_frames=total_frames,
        vocal_ratio=vocal_ratio,
    )


def find_vocal_onset_before(
    vocal_track: list[int],
    position_ms: float,
    min_confidence: int = 3,
    min_duration_ms: float = 2000.0,
    max_search_ms: float = 120000.0,  # 2 minutes
) -> VocalRegion | None:
    """
    Find the last vocal onset before a given position.

    Args:
        vocal_track: PVDI vocal track data
        position_ms: Position to search before (in ms)
        min_confidence: Minimum confidence threshold
        min_duration_ms: Minimum vocal region duration
        max_search_ms: Maximum time to search backwards

    Returns:
        VocalRegion if found, None otherwise
    """
    result = analyze_vocal_track(vocal_track, min_confidence, min_duration_ms)

    # Filter regions before position
    before_regions = [r for r in result.regions if r.end_ms <= position_ms]

    if not before_regions:
        return None

    # Return the last (closest) region
    return max(before_regions, key=lambda r: r.start_ms)


def find_vocal_onset_after(
    vocal_track: list[int],
    position_ms: float,
    min_confidence: int = 3,
    min_duration_ms: float = 2000.0,
) -> VocalRegion | None:
    """
    Find the first vocal onset after a given position.

    Args:
        vocal_track: PVDI vocal track data
        position_ms: Position to search after (in ms)
        min_confidence: Minimum confidence threshold
        min_duration_ms: Minimum vocal region duration

    Returns:
        VocalRegion if found, None otherwise
    """
    result = analyze_vocal_track(vocal_track, min_confidence, min_duration_ms)

    # Filter regions after position
    after_regions = [r for r in result.regions if r.start_ms >= position_ms]

    if not after_regions:
        return None

    # Return the first (closest) region
    return min(after_regions, key=lambda r: r.start_ms)


def get_vocal_confidence_at(
    vocal_track: list[int], position_ms: float
) -> int:
    """Get vocal confidence at a specific position."""
    frame = int(position_ms / PVDI_FRAME_MS)
    if 0 <= frame < len(vocal_track):
        return vocal_track[frame]
    return 0


def has_vocal_at(
    vocal_track: list[int], position_ms: float, threshold: int = 1
) -> bool:
    """Check if there's vocal at a specific position."""
    return get_vocal_confidence_at(vocal_track, position_ms) >= threshold


def snap_to_vocal_phrase(
    vocal_track: list[int],
    position_ms: float,
    phrases: list,
    beat_grid: "BeatGrid",
    max_distance_bars: int = 4,
) -> float | None:
    """
    Snap a vocal position to the nearest phrase boundary.

    Args:
        vocal_track: PVDI vocal track data
        position_ms: Vocal position to snap
        phrases: List of Phrase objects
        beat_grid: BeatGrid for snapping
        max_distance_bars: Maximum distance in bars to search for phrase

    Returns:
        Snapped position in ms, or None if no suitable phrase found
    """
    max_distance_ms = beat_grid.bars_to_ms(max_distance_bars)

    best_phrase = None
    best_dist = float("inf")

    for phrase in phrases:
        dist = abs(phrase.position_ms - position_ms)
        if dist < best_dist and dist < max_distance_ms:
            best_dist = dist
            best_phrase = phrase

    if best_phrase:
        return best_phrase.position_ms

    # Fallback: snap to nearest bar
    return beat_grid.snap_to_bar(position_ms)