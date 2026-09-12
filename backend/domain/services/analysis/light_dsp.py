"""Bounded NumPy-only estimates: no JIT, ML model, resampling or beat tracker.

These are excerpt estimates, not a beat grid. Detailed analysis remains the
route to a whole-track grid and higher-quality tonal/timbre features.
"""
import numpy as np

SAMPLE_RATE = 11025
WINDOW_SECONDS = 30
WORKER_TIMEOUT = 60.0
FRAME_SIZE = 2048
HOP_SIZE = 128


def rhythm_and_key(audio):
    audio = np.asarray(audio, dtype=np.float32)
    if audio.ndim != 1 or not audio.size or not np.isfinite(audio).all():
        raise ValueError("Audio is empty or contains non-finite samples")
    if len(audio) > SAMPLE_RATE * WINDOW_SECONDS:
        raise ValueError("Light DSP requires a bounded excerpt")
    if len(audio) < FRAME_SIZE:
        audio = np.pad(audio, (0, FRAME_SIZE - len(audio)))
    frames = np.lib.stride_tricks.sliding_window_view(audio, FRAME_SIZE)[::HOP_SIZE]
    window = np.hanning(FRAME_SIZE)
    onset = np.zeros(len(frames), dtype=np.float64)
    tonal_spectrum = np.zeros(FRAME_SIZE // 2 + 1)
    previous = None
    # Keep FFT temporaries small even on a memory-constrained machine.
    for start in range(0, len(frames), 64):
        spectrum = np.abs(np.fft.rfft(frames[start:start + 64] * window, axis=1))
        tonal_spectrum += np.sum(spectrum ** 2, axis=0)
        compressed = np.log1p(spectrum)
        before = np.vstack([compressed[:1] if previous is None else previous, compressed[:-1]])
        onset[start:start + len(spectrum)] = np.mean(np.maximum(compressed - before, 0), axis=1)
        previous = compressed[-1:]

    bpm, confidence = _tempo(onset)
    key, scale, strength = _key(tonal_spectrum)
    return bpm, confidence, key, scale, strength


def _tempo(onset):
    if len(onset) < 4 or np.max(onset) < 1e-5:
        return 0.0, 0.0
    # Remove steady energy before correlating; zero-pad to avoid circular lags.
    envelope = np.maximum(onset - np.median(onset), 0)
    size = 1 << (2 * len(envelope) - 1).bit_length()
    spectrum = np.fft.rfft(envelope, n=size)
    correlation = np.fft.irfft(np.abs(spectrum) ** 2, n=size)[:len(envelope)]
    if correlation[0] <= 1e-12:
        return 0.0, 0.0
    rate = SAMPLE_RATE / HOP_SIZE
    first = max(1, int(rate * 60 / 240))
    last = min(len(envelope) - 2, int(rate * 60 / 60))
    if last <= first:
        return 0.0, 0.0
    lags = np.arange(first, last + 1)
    peaks = lags[(correlation[lags] >= correlation[lags - 1])
                 & (correlation[lags] >= correlation[lags + 1])]
    if not peaks.size:
        return 0.0, 0.0
    # Repeated multiples can be nearly as strong as the fundamental pulse.
    # Prefer the shortest comparable peak rather than biasing fast tracks to
    # half tempo with a hard-coded 120 BPM prior.
    contenders = peaks[correlation[peaks] >= .98 * np.max(correlation[peaks])]
    lag = int(contenders[0])
    left, peak, right = correlation[lag - 1:lag + 2]
    denominator = left - 2 * peak + right
    offset = float(np.clip(.5 * (left - right) / denominator, -.5, .5)) if denominator < 0 else 0.0
    confidence = float(np.clip(peak / correlation[0], 0, 1))
    return float(60 * rate / (lag + offset)), confidence


def _key(power):
    frequencies = np.fft.rfftfreq(FRAME_SIZE, 1 / SAMPLE_RATE)
    # Tonal local maxima avoid spreading a single note across pitch classes.
    peaks = np.flatnonzero((power[1:-1] > power[:-2]) & (power[1:-1] >= power[2:])) + 1
    peaks = peaks[(frequencies[peaks] >= 65) & (frequencies[peaks] <= 4000)]
    chroma = np.zeros(12)
    if peaks.size:
        logs = np.log(np.maximum(power, 1e-20))
        denominator = logs[peaks - 1] - 2 * logs[peaks] + logs[peaks + 1]
        offsets = np.divide(.5 * (logs[peaks - 1] - logs[peaks + 1]), denominator,
                            out=np.zeros(len(peaks)), where=np.abs(denominator) > 1e-12)
        pitches = 69 + 12 * np.log2((peaks + np.clip(offsets, -.5, .5)) * SAMPLE_RATE / FRAME_SIZE / 440)
        np.add.at(chroma, np.rint(pitches).astype(int) % 12, np.sqrt(power[peaks]))
    centered = chroma - chroma.mean()
    major = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
    minor = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17])
    scores = []
    for profile in (major, minor):
        profile = profile - profile.mean()
        denominator = max(np.linalg.norm(centered) * np.linalg.norm(profile), 1e-12)
        scores.extend(float(np.dot(centered, np.roll(profile, pitch)) / denominator) for pitch in range(12))
    best = int(np.argmax(scores))
    return (["C", "C#", "D", "Eb", "E", "F", "F#", "G", "Ab", "A", "Bb", "B"][best % 12],
            "major" if best < 12 else "minor", max(0.0, scores[best]))
