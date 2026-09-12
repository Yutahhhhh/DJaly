"""Whole-track beat tracking at 11.025 kHz, without JIT or ML dependencies.

Track a locally estimated pulse through the onset envelope. Retain detected
timestamps (including tempo changes); the shared grid fitter only regularizes
tracks whose residuals prove a constant tempo. No downbeat is invented.
"""
import numpy as np

from .light_dsp import SAMPLE_RATE, HOP_SIZE, WINDOW_SECONDS, _tempo, rhythm_and_key
from .beat_grid import playback_grid
from .progress import report

MAX_SECONDS = 1800


def analyze(audio, bpm_hint=None):
    audio = np.asarray(audio, dtype=np.float32)
    if (audio.ndim != 1 or len(audio) < SAMPLE_RATE * 5
            or len(audio) > SAMPLE_RATE * MAX_SECONDS or not np.isfinite(audio).all()):
        raise ValueError("ビート解析には5秒以上30分以内の音源が必要です")
    if bpm_hint is None:
        start = max(0, (len(audio) - SAMPLE_RATE * WINDOW_SECONDS) // 2)
        bpm_hint = rhythm_and_key(audio[start:start + SAMPLE_RATE * WINDOW_SECONDS])[0]
    # A short spectral window localizes attacks; chunked FFTs bound memory.
    size = 512
    padded = np.pad(audio, (size // 2, size // 2))
    frames = np.lib.stride_tricks.sliding_window_view(padded, size)[::HOP_SIZE]
    onset = np.zeros(len(frames))
    previous = None
    window = np.hanning(size)
    for start in range(0, len(frames), 128):
        spectrum = np.log1p(np.abs(np.fft.rfft(frames[start:start + 128] * window, axis=1)))
        before = np.vstack([spectrum[:1] if previous is None else previous, spectrum[:-1]])
        onset[start:start + len(spectrum)] = np.mean(np.maximum(spectrum - before, 0), axis=1)
        previous = spectrum[-1:]

    rate = SAMPLE_RATE / HOP_SIZE
    width = int(24 * rate)
    centers = np.arange(0, len(onset), int(8 * rate))
    tempos, confidence = [], []
    for center in centers:
        left = max(0, min(int(center - width // 2), len(onset) - width))
        bpm, strength = _tempo(onset[left:left + width])
        # Resolve octave ambiguity against the longer-window estimate, while
        # allowing local tempo changes (e.g. a 126 -> 93 BPM transition edit).
        if bpm > 0 and bpm_hint and bpm_hint > 0:
            while bpm < bpm_hint * .65:
                bpm *= 2
            while bpm > bpm_hint * 1.5:
                bpm /= 2
        tempos.append(bpm)
        confidence.append(strength)
    valid = np.array(tempos) > 0
    if not valid.any() or np.max(onset) < 1e-5:
        raise ValueError("音源からビートを検出できませんでした")
    # Interpolate through silent/uncertain sections using nearby actual tempo
    # estimates. This also avoids a single global BPM flattening a tempo change.
    periods = np.interp(np.arange(len(onset)), centers[valid],
                        60 * rate / np.array(tempos)[valid])
    envelope = onset / max(float(np.std(onset)), 1e-8)
    scores = np.zeros(len(onset))
    previous_beat = np.full(len(onset), -1, dtype=np.int32)
    for i, period in enumerate(periods):
        lags = np.arange(max(1, int(period * .55)), int(period * 1.8) + 1)
        lags = lags[lags <= i]
        if len(lags):
            candidates = scores[i - lags] - 100 * np.log(lags / period) ** 2
            best = int(np.argmax(candidates))
            if candidates[best] > 0:
                previous_beat[i] = i - lags[best]
                scores[i] = candidates[best]
        scores[i] += envelope[i]
        if i and i % int(rate * 30) == 0:
            report("beat_grid", f"全曲のビートを解析しています（{min(int(i / rate), int(len(audio) / SAMPLE_RATE))} / {int(len(audio) / SAMPLE_RATE)}秒）")

    end = int(np.argmax(scores))
    beats = []
    while end >= 0:
        beats.append(end)
        end = int(previous_beat[end])
    beats.reverse()
    # Do not extrapolate a beat sequence into a silent intro/outro.
    audible = np.flatnonzero(onset > np.max(onset) * .05)
    beats = [i for i in beats if audible[0] <= i <= audible[-1]]
    if len(beats) < 2:
        raise ValueError("音源から十分なビートを検出できませんでした")
    ticks = np.array(beats) / rate
    intervals = np.diff(ticks)
    bpm = float(60 / np.median(intervals))
    grid = playback_grid(ticks, bpm)
    return grid["bpm"], ticks, float(np.mean(np.array(confidence)[valid]))


def waveform_peaks(audio, count=500):
    # Full-track overview; native playback still generates its detailed waveform.
    edges = np.linspace(0, len(audio), min(count, len(audio)) + 1, dtype=int)
    peaks = np.array([np.max(np.abs(audio[a:b])) for a, b in zip(edges[:-1], edges[1:])])
    return (peaks / max(float(np.max(peaks)), 1e-8)).clip(0, 1).tolist()
