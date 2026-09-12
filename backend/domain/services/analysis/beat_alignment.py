"""Offline attack alignment of beat detections, with bounded NumPy work.

Rhythm trackers estimate pulse phase from spectral windows, not sample attacks.
Refine only a nearby, prominent rise; never seek a different half/whole beat,
regularize tempo, or move a user's or rekordbox's grid here.
"""
import numpy as np


def align_beats(audio, ticks, sample_rate):
    ticks = np.asarray(ticks, dtype=float)
    if len(ticks) < 2:
        return ticks
    hop = max(1, round(sample_rate / 1000))
    count = len(audio) // hop
    if count < 20:
        return ticks
    energy = np.zeros(count)
    # No full-track float64 PCM copy, including for 30-minute files.
    for start in range(0, count, 8000):
        end = min(start + 8000, count)
        # First difference suppresses sustained bass/chord energy, so a loud
        # tonal cycle cannot win over the drum attack we are trying to locate.
        chunk = np.asarray(audio[start * hop:end * hop], dtype=float)
        preceding = audio[start * hop - 1] if start else 0
        frames = np.diff(chunk, prepend=preceding).reshape(-1, hop)
        energy[start:end] = np.mean(np.square(frames, dtype=np.float64), axis=1)
    rate = sample_rate / hop
    rise = np.maximum(energy - np.pad(energy[:-5], (5, 0)), 0)
    aligned = ticks.copy()
    matched = np.zeros(len(ticks), dtype=bool)
    for i, tick in enumerate(ticks):
        period = min(ticks[i] - ticks[i - 1] if i else np.inf,
                     ticks[i + 1] - tick if i + 1 < len(ticks) else np.inf)
        radius = min(.080, period * .18)
        left, right = max(0, int((tick - radius) * rate)), min(count, int((tick + radius) * rate) + 1)
        if right <= left:
            continue
        local = rise[left:right]
        peak = left + int(np.argmax(local))
        strength = rise[peak]
        if strength < max(1e-10, np.median(local) * 4, np.max(energy[left:right]) * .08):
            continue
        edge = peak
        while edge > left and rise[edge - 1] > strength * .15:
            edge -= 1
        before = np.mean(energy[max(0, edge - 12):edge]) if edge else 0
        after = np.mean(energy[edge:min(count, edge + 12)])
        if after <= max(1e-10, before * 1.5):
            continue
        aligned[i] = edge / rate
        matched[i] = True
    # Some trackers emit unsupported pickup/trailing ticks while settling.
    # Trim only a short edge when almost all subsequent beats have attacks.
    if len(ticks) >= 16 and matched.mean() > .8:
        first = next((i for i in range(min(3, len(ticks))) if matched[i]), 0)
        last = next((i for i in range(len(ticks) - 1, max(-1, len(ticks) - 4), -1) if matched[i]), len(ticks) - 1)
        aligned = aligned[first:last + 1]
    return aligned
