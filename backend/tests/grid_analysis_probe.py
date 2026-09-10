"""Opt-in real DSP acceptance probe, independent of pytest's global Essentia mocks.

Run: PYTHONPATH=backend backend/.venv/bin/python backend/tests/grid_analysis_probe.py
"""
import json
from pathlib import Path
import tempfile
import time
import wave

import numpy as np

from domain.services.analysis.rhythm_grid import analyze_grid


def main():
    reports = []
    with tempfile.TemporaryDirectory(prefix="plumdeck-grid-probe-") as directory:
        for bpm, phase in [(120, 0.137), (100, 0.271)]:
            sr = 44100
            period = 60 / bpm
            duration = 24
            audio = np.zeros(sr * duration, dtype=np.float32)
            rng = np.random.default_rng(42)
            pulse = (rng.standard_normal(1323) * np.exp(-np.arange(1323) / 220)).astype(np.float32)
            pulse /= np.max(np.abs(pulse))
            times = np.arange(phase, duration - 0.04, period)
            for index, onset in enumerate(times):
                start = round(onset * sr)
                audio[start:start + len(pulse)] += pulse * (0.9 if index % 4 == 0 else 0.6)
            path = Path(directory) / f"click-{bpm}.wav"
            with wave.open(str(path), "wb") as output:
                output.setnchannels(1)
                output.setsampwidth(2)
                output.setframerate(sr)
                output.writeframes((audio * 32767).astype("<i2").tobytes())
            start = time.monotonic()
            result = analyze_grid(str(path))
            ticks = np.array(result["ticks"])
            phase_errors = np.abs((ticks - phase + period / 2) % period - period / 2) * 1000
            report = {"expected_bpm": bpm, "actual_bpm": result["bpm"],
                      "source_phase_ms": phase * 1000, "first_beat_ms": ticks[0] * 1000,
                      "median_phase_error_ms": float(np.median(phase_errors)),
                      "p95_phase_error_ms": float(np.percentile(phase_errors, 95)),
                      "beats": len(ticks), "confidence_raw": result["confidence"],
                      "elapsed_seconds": round(time.monotonic() - start, 2)}
            print(json.dumps(report), flush=True)
            assert abs(result["bpm"] - bpm) < 2
            assert report["median_phase_error_ms"] < 40
            assert report["p95_phase_error_ms"] < 60
            assert ticks[0] > 0
            reports.append(report)
    print(json.dumps({"passed": len(reports)}))


if __name__ == "__main__":
    main()
