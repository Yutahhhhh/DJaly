import numpy as np
import pytest
import builtins
import shutil
import subprocess
import sys
import threading
import wave

from domain.services.analysis.portable import PortableAudioAnalyzer
from domain.services.analysis.light_dsp import SAMPLE_RATE, rhythm_and_key


def fixture_audio(bpm=126, root=0, minor=False, seconds=30, sample_rate=SAMPLE_RATE):
    t = np.arange(sample_rate * seconds) / sample_rate
    audio = np.zeros(len(t))
    for amplitude, interval in zip((.15, .12, .1), (0, 3 if minor else 4, 7)):
        frequency = 440 * 2 ** ((60 + root + interval - 69) / 12)
        audio += amplitude * np.sin(2 * np.pi * frequency * t)
    for beat in np.arange(.25, seconds, 60 / bpm):
        start = int(beat * sample_rate)
        count = min(int(sample_rate * .009), len(audio) - start)
        audio[start:start + count] += .5 * np.exp(-np.arange(count) / (sample_rate * .0016))
    return audio.astype(np.float32)


@pytest.mark.parametrize("bpm", [70, 80, 90, 100, 120, 126, 140, 174, 200, 220])
def test_light_estimates_known_tempos_without_librosa(bpm):
    actual, confidence, key, scale, _ = rhythm_and_key(fixture_audio(bpm=bpm))
    assert abs(actual - bpm) < 1
    assert confidence > .5
    assert (key, scale) == ("C", "major")


@pytest.mark.parametrize("root", range(12))
@pytest.mark.parametrize("minor", [False, True])
def test_light_estimates_transposed_major_and_minor_chords(root, minor):
    _, _, key, scale, strength = rhythm_and_key(fixture_audio(root=root, minor=minor, seconds=5))
    assert key == ["C", "C#", "D", "Eb", "E", "F", "F#", "G", "Ab", "A", "Bb", "B"][root]
    assert scale == ("minor" if minor else "major")
    assert strength > .5


def test_light_rejects_invalid_input_and_does_not_invent_silent_bpm():
    assert rhythm_and_key(np.zeros(SAMPLE_RATE))[0] == 0
    for audio in (np.array([]), np.array([np.nan]), np.ones(SAMPLE_RATE * 31)):
        with pytest.raises(ValueError):
            rhythm_and_key(audio)


@pytest.mark.parametrize("extension", ["wav", "mp3", "flac"])
def test_real_light_decode_and_analysis_never_imports_heavy_runtime(tmp_path, monkeypatch, extension):
    converter = shutil.which("ffmpeg")
    if not converter:
        pytest.skip("FFmpeg required for real decoder test")
    # A stereo 44.1 kHz file longer than the analysis window exercises seeking,
    # channel mixing and decoder-side downsampling. Keep Unicode/spaces in paths.
    source = tmp_path / "音楽 fixture.wav"
    mono = fixture_audio(seconds=40, sample_rate=44100)
    with wave.open(str(source), "wb") as output:
        output.setparams((2, 2, 44100, 0, "NONE", "not compressed"))
        output.writeframes((np.repeat(mono[:, None], 2, axis=1) * 32767).astype("<i2").tobytes())
    path = source
    if extension != "wav":
        path = source.with_suffix("." + extension)
        subprocess.run([converter, "-v", "error", "-i", str(source), str(path)], check=True, timeout=20)
    original_import = builtins.__import__

    def guarded(name, *args, **kwargs):
        if name.split(".")[0] in {"librosa", "numba", "scipy", "onnxruntime", "tensorflow"}:
            raise AssertionError(f"Light analysis imported {name}")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded)
    if extension == "mp3":
        import ingest
        from domain.services.analysis import portable
        monkeypatch.setattr(sys, "platform", "win32")
        monkeypatch.setattr(ingest, "_thread_local", threading.local())
        monkeypatch.setattr(portable, "find_ffmpeg", lambda: converter)
        result = ingest.analyze_track_file(str(path), analysis_profile="light")
    else:
        result = PortableAudioAnalyzer().analyze_light(str(path))
    assert abs(result["bpm"] - 126) < 1
    assert result["key"] == "C major"
    assert abs(result["duration"] - 40) < .2
    assert result["features_extra"]["analysis_window_seconds"] == 30
    assert result["features_extra"]["analysis_window_start_seconds"] == pytest.approx(5, abs=.1)
    assert result["analysis_level"] == "light"
    assert "embedding" not in result


def test_light_features_are_finite_bounded_approximations():
    analyzer = PortableAudioAnalyzer()
    samples = np.arange(44100 * 2, dtype=np.float32)
    envelope = .06 + .04 * np.sin(2 * np.pi * samples / 22050)
    audio = envelope * np.sin(2 * np.pi * 1500 * samples / 44100)

    result = analyzer._extract_light_features(audio.astype(np.float32))

    assert np.isfinite(list(result.values())).all()
    assert 0 < result["energy"] < 1
    assert 0 < result["brightness"] < 1
    assert 0 <= result["noisiness"] <= 1
    assert result["loudness"] < 0
    assert result["loudness_range"] > 0
    assert result["spectral_rolloff"] > 0
