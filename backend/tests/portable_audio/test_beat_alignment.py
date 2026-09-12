import numpy as np
import pytest

from domain.services.analysis.beat_alignment import align_beats
from domain.services.analysis.beat_grid import playback_grid


def audio_fixture(kind, sr=44100, duration=32):
    rng = np.random.default_rng(52)
    audio = np.zeros(sr * duration, np.float32)
    t = np.arange(round(sr * .10)) / sr
    expected, beat = [], .271
    while beat < duration - .15:
        expected.append(beat)
        pulse = (np.sin(2 * np.pi * 65 * t) if kind == "kick" else rng.standard_normal(len(t))) * np.exp(-t / .013)
        i = round(beat * sr)
        audio[i:i + len(t)] += pulse * .4
        if kind == "offbeat" and i + sr // 4 + len(t) < len(audio):
            audio[i + sr // 4:i + sr // 4 + len(t)] += rng.standard_normal(len(t)) * np.exp(-t / .008) * .1
        bpm = (126 if beat < duration / 2 else 93) if kind == "transition" else 120
        beat += 60 / bpm
    return audio, np.array(expected)


@pytest.mark.parametrize("kind", ["click","kick","offbeat","transition"])
@pytest.mark.parametrize("offset", [-.04,.03])
def test_attack_alignment_corrects_either_bias_without_flattening_tempo(kind, offset):
    audio, expected = audio_fixture(kind)
    ticks = expected + offset + .004 * np.sin(np.arange(len(expected)))
    aligned = align_beats(audio, ticks, 44100)
    assert len(aligned) == len(expected)
    assert np.max(np.abs(aligned - expected)) < .002
    assert np.all(np.diff(aligned) > 0)
    if kind == "transition":
        assert playback_grid(aligned,126)["beat_times_ms"] is not None
        assert np.median(np.diff(aligned[expected < 15])) == pytest.approx(60/126, abs=.002)
        assert np.median(np.diff(aligned[expected > 18])) == pytest.approx(60/93, abs=.002)


def test_no_transients_does_not_fabricate_grid_or_mutate_input():
    ticks = np.arange(.2, 10, .5)
    saved = ticks.copy()
    assert np.array_equal(align_beats(np.zeros(441000),ticks,44100),ticks)
    assert np.array_equal(ticks,saved)


@pytest.mark.parametrize("kind", ["click","kick","offbeat","transition"])
def test_real_essentia_detections_are_aligned_to_known_attacks(kind):
    es = pytest.importorskip("essentia.standard")
    audio, expected = audio_fixture(kind, duration=64)
    bpm,ticks,*_ = es.RhythmExtractor2013(method="multifeature")(audio)
    aligned = align_beats(audio,ticks,44100)
    errors = np.min(np.abs(aligned[:,None] - expected[None,:]),axis=1)
    assert np.percentile(errors,95) < .003
    assert len(aligned) > len(expected) * .93
