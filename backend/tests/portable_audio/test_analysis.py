import numpy as np
import pytest

from domain.services.analysis.portable import PortableAudioAnalyzer, musicnn_bands


@pytest.mark.parametrize("samples", [8192, 8193, 16000])
def test_musicnn_frontend_matches_reference(samples):
    es = pytest.importorskip("essentia.standard")
    audio = np.random.default_rng(42).normal(0, .1, samples).astype(np.float32)
    actual = musicnn_bands(audio)
    frames = es.FrameGenerator(audio, frameSize=512, hopSize=256)
    expected = np.array([es.TensorflowInputMusiCNN()(frame) for frame in frames])
    np.testing.assert_allclose(actual, expected, atol=5e-5, rtol=5e-5)


def test_silent_audio_has_finite_timbre_and_no_rhythm():
    analyzer = PortableAudioAnalyzer()
    audio = np.zeros(44100, dtype=np.float32)
    assert analyzer._rhythm(audio)[0] == 0
    assert np.isfinite(list(analyzer._extract_timbre_features(audio).values())).all()


def test_selective_waveform_does_not_load_embedding_model():
    analyzer = PortableAudioAnalyzer()
    analyzer._load_audio = lambda _: np.ones(44100, dtype=np.float32) * .5
    result = analyzer.analyze_selected("fixture", ["waveform"])
    assert result["features_extra"]["waveform_peaks"] == [.5] * 500
    assert analyzer._embedding_session is None


def test_malformed_audio_does_not_become_success(tmp_path):
    path = tmp_path / "音楽 file.mp3"
    path.write_bytes(b"not audio")
    with pytest.raises(Exception):
        PortableAudioAnalyzer().analyze_selected(str(path), ["waveform"])
