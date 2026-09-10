"""Explicit CLI diagnostic used to validate the *packaged* analysis runtime."""
import json
from pathlib import Path
import tempfile
import wave


def run():
    import numpy as np
    from domain.services.analysis.analyzer import AudioAnalyzer
    sr = 44100
    t = np.arange(sr * 12) / sr
    audio = sum(.12 * np.sin(2 * np.pi * frequency * t) for frequency in (261.626, 329.628, 391.995))
    for beat in np.arange(.25, 12, .5):
        start = int(beat * sr)
        audio[start:start+400] += .5 * np.exp(-np.arange(400) / 70)
    with tempfile.TemporaryDirectory(prefix="Plumdeck 音楽 ") as directory:
        path = Path(directory) / "analysis fixture.wav"
        with wave.open(str(path), "wb") as output:
            output.setparams((1, 2, sr, 0, "NONE", "not compressed"))
            output.writeframes((np.clip(audio, -1, 1) * 32767).astype("<i2").tobytes())
        result = AudioAnalyzer().analyze_selected(str(path), ["rhythm", "key", "timbre", "waveform", "embedding"])
    assert abs(result["bpm"] - 120) < 3, result["bpm"]
    assert result["key"] == "C major", result["key"]
    assert len(result["embedding"]) == 200
    assert np.isfinite(result["embedding"]).all() and np.linalg.norm(result["embedding"]) > 0
    assert len(result["features_extra"]["waveform_peaks"]) == 500
    assert len(result["features_extra"]["beat_positions"]) >= 16
    print(json.dumps({"ok": True, "bpm": result["bpm"], "key": result["key"], "embeddingDimensions": 200}))


if __name__ == "__main__":
    run()
