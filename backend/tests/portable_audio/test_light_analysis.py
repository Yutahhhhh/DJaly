import numpy as np

from domain.services.analysis.portable import PortableAudioAnalyzer


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
