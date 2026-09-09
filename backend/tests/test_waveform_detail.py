import math
from pathlib import Path
import wave

import numpy as np
import pytest

from app.services import waveform_detail_service as service
from domain.models.track import Track


def _write_wave(path: Path, samples: np.ndarray):
    with wave.open(str(path), "wb") as output:
        output.setparams((1, 2, service.SAMPLE_RATE, 0, "NONE", "not compressed"))
        output.writeframes((samples * 32767).astype("<i2").tobytes())


def _track(session, filepath):
    track = Track(filepath=str(filepath), title="Waveform fixture", duration=3)
    session.add(track)
    session.commit()
    session.refresh(track)
    return track


def test_detail_endpoint_decodes_300_real_bins_per_second_and_frequency_bands(client, session, tmp_path, monkeypatch):
    monkeypatch.setattr(service, "_cache_dir", lambda: tmp_path / "cache")
    time = np.arange(service.SAMPLE_RATE) / service.SAMPLE_RATE
    audio = np.concatenate([0.7 * np.sin(2 * np.pi * hz * time) for hz in (100, 1000, 6000)])
    source = tmp_path / "bands.wav"
    _write_wave(source, audio)
    source_bytes = source.read_bytes()
    track = _track(session, source)
    response = client.get(f"/api/play/tracks/{track.id}/waveform-detail")
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["source"] == "decoded-audio"
    assert result["bins_per_second"] == 300
    assert result["duration_ms"] == pytest.approx(3000)
    assert len(result["peaks"]) == 900
    assert result["amplitude_scale"] == 255
    bands = np.array([result["low"], result["mid"], result["high"]])
    for second in range(3):
        means = bands[:, second * 300 + 30:(second + 1) * 300].mean(axis=1)
        assert np.argmax(means) == second
    assert source.read_bytes() == source_bytes
    assert len(list((tmp_path / "cache").glob("*.npz"))) == 1


def test_transient_timing_and_partial_final_bin_are_preserved(tmp_path):
    audio = np.zeros(service.SAMPLE_RATE + 17)
    audio[12_010:12_030] = 0.8
    audio[-1] = 0.6
    source = tmp_path / "transient.wav"
    _write_wave(source, audio)
    values, samples = service._decode(source)
    assert samples == len(audio)
    assert len(values) == math.ceil(len(audio) / service.SAMPLES_PER_BIN)
    assert np.argmax(values[:, 0]) == 150
    assert np.count_nonzero(values[:, 0]) == 2
    assert values[-1, 0] > 100


def test_cache_reuses_decode_and_invalidates_when_source_changes(tmp_path, monkeypatch):
    monkeypatch.setattr(service, "_cache_dir", lambda: tmp_path / "cache")
    source = tmp_path / "source.wav"
    _write_wave(source, np.zeros(240))
    calls = []

    def decode(_):
        calls.append(True)
        return np.full((3, 4), len(calls), dtype=np.uint8), 240

    monkeypatch.setattr(service, "_decode", decode)
    first = service.waveform_detail(str(source))
    assert service.waveform_detail(str(source)) == first
    assert len(calls) == 1
    _write_wave(source, np.zeros(320))
    assert service.waveform_detail(str(source))["peaks"] != first["peaks"]
    assert len(calls) == 2


def test_disposable_cache_is_bounded(tmp_path, monkeypatch):
    monkeypatch.setattr(service, "_cache_dir", lambda: tmp_path / "cache")
    monkeypatch.setattr(service, "CACHE_MAX_FILES", 2)
    monkeypatch.setattr(service, "_decode", lambda _: (np.ones((3, 4), dtype=np.uint8), 240))
    for index in range(4):
        source = tmp_path / f"source-{index}.wav"
        _write_wave(source, np.zeros(240))
        service.waveform_detail(str(source))
    assert len(list((tmp_path / "cache").glob("*.npz"))) == 2


def test_unknown_track_missing_source_and_invalid_audio_are_explicit(client, session, tmp_path, monkeypatch):
    monkeypatch.setattr(service, "_cache_dir", lambda: tmp_path / "cache")
    assert client.get("/api/play/tracks/999999999/waveform-detail").status_code == 404
    missing = _track(session, tmp_path / "missing.wav")
    assert client.get(f"/api/play/tracks/{missing.id}/waveform-detail").status_code == 404
    invalid = tmp_path / "invalid.wav"
    invalid.write_bytes(b"not audio")
    broken = _track(session, invalid)
    response = client.get(f"/api/play/tracks/{broken.id}/waveform-detail")
    assert response.status_code == 422
    assert "デコード" in response.json()["detail"]


def test_downsample_keeps_peaks_and_reports_matching_density():
    """一覧のプレビュー用に間引く。平均だと立ち上がりが潰れるので最大値を採る。"""
    import numpy as np
    from app.services.waveform_detail_service import _downsample, _payload, SAMPLE_RATE

    values = np.zeros((1000, 4), dtype=np.uint8)
    values[123] = [255, 200, 150, 100]  # 単発のピーク
    reduced = _downsample(values, 10)

    assert reduced.shape == (10, 4)
    # 123 は 2 番目のグループ（100..199）に入り、その最大値として残る。
    assert reduced[1].tolist() == [255, 200, 150, 100]
    assert reduced[:, 0].max() == 255, "ピークが平均で消えてはいけない"

    samples = SAMPLE_RATE * 10  # 10 秒
    payload = _payload(values, samples, bins=10)
    assert len(payload["peaks"]) == 10
    assert len(payload["low"]) == len(payload["mid"]) == len(payload["high"]) == 10
    # 間引いた分だけ密度も下がっていないと、時間軸の対応が狂う。
    assert payload["bins_per_second"] == 10 / (payload["duration_ms"] / 1000)


def test_downsample_is_a_no_op_when_bins_cover_everything():
    import numpy as np
    from app.services.waveform_detail_service import _downsample

    values = np.arange(40, dtype=np.uint8).reshape(10, 4)
    assert _downsample(values, 10) is values
    assert _downsample(values, 99) is values
    assert _downsample(values, 0) is values
