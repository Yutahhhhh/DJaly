"""Fit a playback grid offline; retain raw detections for future re-analysis.

Only convincingly constant tempo is regularized. Imported/manual grids never
pass through this function. No downbeat is inferred from beat-only detections.
"""
import math

VERSION = 1


def playback_grid(ticks, bpm, confidence=None):
    ticks = [float(t) for t in ticks]
    if len(ticks) < 2:
        return None
    if not math.isfinite(float(bpm)) or not 20 <= float(bpm) <= 300:
        return None
    if any(not math.isfinite(t) or t < 0 for t in ticks) or any(b <= a for a, b in zip(ticks, ticks[1:])):
        raise ValueError("Invalid beat timestamps")
    grid = dict(bpm=float(bpm), first_beat_ms=ticks[0] * 1000,
                beat_times_ms=[t * 1000 for t in ticks], source="analysis", confidence=confidence)
    if len(ticks) < 16:
        return grid
    n = len(ticks)
    center = (n - 1) / 2
    mean = math.fsum(ticks) / n
    period = math.fsum((i - center) * (t - mean) for i, t in enumerate(ticks)) / (n * (n*n - 1) / 12)
    origin = mean - period * center
    residuals = sorted(abs(t - (origin + i * period)) for i, t in enumerate(ticks))
    # A whole-track fit prevents accumulating rounding drift. Reject real tempo
    # changes, missing beats, and uncertain detections instead of flattening them.
    if origin >= 0 and 0.2 <= period <= 3 and residuals[math.ceil(n * .95) - 1] <= .020 and residuals[-1] <= .050:
        grid.update(bpm=60 / period, first_beat_ms=origin * 1000, beat_times_ms=None)
    return grid
