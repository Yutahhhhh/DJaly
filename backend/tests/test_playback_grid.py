import math
import pytest
from domain.services.analysis.beat_grid import playback_grid


def test_constant_tempo_removes_detection_jitter_without_rounding_drift():
    ticks = [.137 + i * (60 / 123.456) + .008 * math.sin(i * 1.7) for i in range(1200)]
    grid = playback_grid(ticks, 123.46, 4.5)
    assert grid['beat_times_ms'] is None
    assert grid['bpm'] == pytest.approx(123.456, abs=.001)
    assert abs(grid['first_beat_ms'] + 1199 * 60000 / grid['bpm'] - (.137 + 1199 * 60 / 123.456) * 1000) < 1
    assert 'beat_numbers' not in grid


@pytest.mark.parametrize('ticks', [
    [.2 + i * .5 + .0002 * i*i for i in range(200)],
    [.2 + i * .5 + (0 if i < 80 else .5) for i in range(200)],
    [.2, .71, 1.19],
])
def test_variable_tempo_missing_beats_and_short_detections_are_preserved(ticks):
    assert playback_grid(ticks, 120)['beat_times_ms'] == [t * 1000 for t in ticks]


def test_invalid_detections_are_rejected():
    with pytest.raises(ValueError):
        playback_grid([.2, .1], 120)
