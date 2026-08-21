"""Tests for BeatGrid domain logic."""

from __future__ import annotations

import pytest

from rekordbox_mcp.domain.beatgrid import (
    BeatGrid,
    create_beat_grid_from_analysis,
    estimate_beat_grid_from_bpm,
)


class TestBeatToMs:
    def test_first_beat_is_first_beat_ms(self, sample_beatgrid: BeatGrid):
        assert sample_beatgrid.beat_to_ms(1) == pytest.approx(100.0)

    def test_second_beat_advances_by_ms_per_beat(self, sample_beatgrid: BeatGrid):
        expected = 100.0 + sample_beatgrid.ms_per_beat
        assert sample_beatgrid.beat_to_ms(2) == pytest.approx(expected)

    def test_beat_below_one_clamped_to_one(self, sample_beatgrid: BeatGrid):
        assert sample_beatgrid.beat_to_ms(0) == sample_beatgrid.beat_to_ms(1)
        assert sample_beatgrid.beat_to_ms(-5) == sample_beatgrid.beat_to_ms(1)

    def test_ms_per_beat_matches_bpm(self):
        bg = BeatGrid(first_beat_ms=0.0, bpm=120.0)
        assert bg.ms_per_beat == pytest.approx(500.0)


class TestMsToBeat:
    def test_ms_to_beat_roundtrip(self, sample_beatgrid: BeatGrid):
        for beat in (1, 2, 5, 17):
            ms = sample_beatgrid.beat_to_ms(beat)
            assert sample_beatgrid.ms_to_beat(ms) == beat

    def test_ms_before_first_beat_clamped_to_one(self, sample_beatgrid: BeatGrid):
        assert sample_beatgrid.ms_to_beat(0.0) == 1

    def test_ms_to_beat_exact_is_fractional(self, sample_beatgrid: BeatGrid):
        half_beat_ms = sample_beatgrid.first_beat_ms + sample_beatgrid.ms_per_beat * 0.5
        exact = sample_beatgrid.ms_to_beat_exact(half_beat_ms)
        assert exact == pytest.approx(1.5)


class TestSnapping:
    def test_snap_to_beat_rounds_to_nearest_beat(self, sample_beatgrid: BeatGrid):
        near_beat_2 = sample_beatgrid.beat_to_ms(2) + 5.0
        snapped = sample_beatgrid.snap_to_beat(near_beat_2)
        assert snapped == pytest.approx(sample_beatgrid.beat_to_ms(2))

    def test_snap_to_bar_rounds_down_to_bar_start(self, sample_beatgrid: BeatGrid):
        # Beat 6 is within bar starting at beat 5 (bars are 4 beats)
        beat_6_ms = sample_beatgrid.beat_to_ms(6)
        snapped = sample_beatgrid.snap_to_bar(beat_6_ms)
        assert snapped == pytest.approx(sample_beatgrid.beat_to_ms(5))

    def test_snap_to_grid_half_beat(self, sample_beatgrid: BeatGrid):
        target = sample_beatgrid.first_beat_ms + sample_beatgrid.ms_per_beat * 1.5
        snapped = sample_beatgrid.snap_to_grid(target + 2.0, grid="half_beat")
        assert snapped == pytest.approx(target)

    def test_snap_to_grid_quarter_beat(self, sample_beatgrid: BeatGrid):
        target = sample_beatgrid.first_beat_ms + sample_beatgrid.ms_per_beat * 1.25
        snapped = sample_beatgrid.snap_to_grid(target + 1.0, grid="quarter_beat")
        assert snapped == pytest.approx(target)

    def test_snap_to_grid_unknown_falls_back_to_beat(self, sample_beatgrid: BeatGrid):
        ms = sample_beatgrid.beat_to_ms(3) + 3.0
        assert sample_beatgrid.snap_to_grid(ms, grid="beat") == sample_beatgrid.snap_to_beat(ms)


class TestBarsToMs:
    def test_bars_to_ms_uses_four_beats_per_bar(self, sample_beatgrid: BeatGrid):
        assert sample_beatgrid.bars_to_ms(1) == pytest.approx(sample_beatgrid.ms_per_beat * 4)
        assert sample_beatgrid.bars_to_ms(4) == pytest.approx(sample_beatgrid.ms_per_beat * 16)

    def test_ms_to_bar(self, sample_beatgrid: BeatGrid):
        assert sample_beatgrid.ms_to_bar(sample_beatgrid.beat_to_ms(1)) == 1
        assert sample_beatgrid.ms_to_bar(sample_beatgrid.beat_to_ms(5)) == 2

    def test_get_bar_start_ms(self, sample_beatgrid: BeatGrid):
        assert sample_beatgrid.get_bar_start_ms(1) == pytest.approx(sample_beatgrid.beat_to_ms(1))
        assert sample_beatgrid.get_bar_start_ms(3) == pytest.approx(sample_beatgrid.beat_to_ms(9))

    def test_get_bar_start_ms_below_one_clamped(self, sample_beatgrid: BeatGrid):
        assert sample_beatgrid.get_bar_start_ms(0) == sample_beatgrid.get_bar_start_ms(1)


class TestCreateBeatGridFromAnalysis:
    def test_bpm_times_100_conversion(self):
        bg = create_beat_grid_from_analysis(first_beat_ms=250.0, bpm_times_100=12800)
        assert bg.bpm == pytest.approx(128.0)
        assert bg.first_beat_ms == pytest.approx(250.0)

    def test_returns_beatgrid_instance(self):
        bg = create_beat_grid_from_analysis(first_beat_ms=0.0, bpm_times_100=13000)
        assert isinstance(bg, BeatGrid)
        assert bg.bpm == pytest.approx(130.0)


class TestEstimateBeatGridFromBpm:
    def test_defaults_first_beat_to_zero(self):
        bg = estimate_beat_grid_from_bpm(140.0)
        assert bg.first_beat_ms == 0.0
        assert bg.bpm == 140.0

    def test_explicit_first_beat(self):
        bg = estimate_beat_grid_from_bpm(140.0, first_beat_ms=500.0)
        assert bg.first_beat_ms == 500.0


class TestModelConversion:
    def test_to_model_and_from_model_roundtrip(self, sample_beatgrid: BeatGrid):
        model = sample_beatgrid.to_model()
        assert model.first_beat_ms == sample_beatgrid.first_beat_ms
        assert model.bpm == sample_beatgrid.bpm

        restored = BeatGrid.from_model(model)
        assert restored == sample_beatgrid


class TestGetBeatPosition:
    def test_beat_position_details(self, sample_beatgrid: BeatGrid):
        ms = sample_beatgrid.beat_to_ms(6)
        info = sample_beatgrid.get_beat_position(ms)
        assert info["beat"] == 6
        assert info["bar"] == 2
        assert info["beat_in_bar"] == 2
