"""Tests for CueStrategy cue-generation logic."""

from __future__ import annotations

import pytest

from rekordbox_mcp.domain.beatgrid import BeatGrid
from rekordbox_mcp.domain.models import CueProfile, CueProposal, Track
from rekordbox_mcp.domain.strategy import CueStrategy, CueStrategyConfig, create_cue_strategy


class TestCueProfileCsv:
    def test_from_csv_loads_slots_and_colors(self, tmp_path):
        path = tmp_path / "club.csv"
        path.write_text(
            "Label,Hot Cue,Color,Label,Memory Cue,Memory Offset Bars\n"
            "A,Intro,Green,1,Intro,0\n"
            "B,Loop,Red,2,Loop,0\n"
            "C,Buildup,Blue,3,Buildup,8\n"
            "D,Drop,Yellow,4,Drop,16\n"
            "E,Break, Cyan,5,Break,16\n"
            "F,Special,Purple,6,Special,16\n"
            "G,Outro,Orange,7,Outro,16\n"
            "H,Loop Out,White,8,Loop Out,0\n",
            encoding="utf-8",
        )

        profile = CueProfile.from_csv(path)

        assert profile.name == "club"
        assert [slot.kind for slot in profile.slots] == [1, 2, 3, 5, 6, 7, 8, 9]
        assert profile.slots[0].hot_cue_color_table_index == 18
        assert profile.slots[0].memory_cue_color == 4
        assert profile.slots[2].memory_offset_bars == 8
        assert profile.slots[4].hot_cue_color_table_index == 9
        assert profile.slots[7].is_loop


class TestProposeReturnsProposal:
    def test_propose_returns_cue_proposal(self, sample_track: Track):
        strategy = CueStrategy()
        proposal = strategy.propose(sample_track)

        assert isinstance(proposal, CueProposal)
        assert proposal.track_id == sample_track.id

    def test_propose_without_beatgrid_raises(self, sample_track: Track):
        sample_track.beat_grid = None
        strategy = CueStrategy()
        with pytest.raises(ValueError):
            strategy.propose(sample_track)

    def test_propose_includes_confidence_and_notes(self, sample_track: Track):
        strategy = CueStrategy()
        proposal = strategy.propose(sample_track)

        assert "A" in proposal.confidence
        assert proposal.confidence["A"] == pytest.approx(1.0)
        assert len(proposal.notes) > 0


class TestPhraseBasedPlacement:
    def test_drop_placed_at_chorus_after_20_percent(self, sample_track: Track, sample_beatgrid: BeatGrid):
        strategy = CueStrategy()
        proposal = strategy.propose(sample_track)

        drop_cues = [c for c in proposal.hot_cues if c.comment == "Drop"]
        assert len(drop_cues) == 1

        chorus_phrase = next(p for p in sample_track.phrases if p.label == "Chorus")
        assert drop_cues[0].position_ms == pytest.approx(chorus_phrase.position_ms)

    def test_outro_placed_at_outro_phrase(self, sample_track: Track):
        strategy = CueStrategy()
        proposal = strategy.propose(sample_track)

        outro_cues = [c for c in proposal.hot_cues if c.comment == "Outro"]
        assert len(outro_cues) == 1

        outro_phrase = next(p for p in sample_track.phrases if p.label == "Outro")
        assert outro_cues[0].position_ms == pytest.approx(outro_phrase.position_ms)

    def test_no_chorus_results_in_no_drop_cue(self, sample_track: Track):
        sample_track.phrases = [p for p in sample_track.phrases if p.label != "Chorus"]
        strategy = CueStrategy()
        proposal = strategy.propose(sample_track)

        assert proposal.confidence["D"] == 0.0
        drop_cues = [c for c in proposal.hot_cues if c.comment == "Drop"]
        assert len(drop_cues) == 0

    def test_no_phrases_at_all_results_in_no_outro(self, sample_beatgrid: BeatGrid):
        track = Track(
            id=99,
            title="Empty",
            artist="Nobody",
            bpm=sample_beatgrid.bpm,
            duration_ms=200000.0,
            analysis_path="/mock/none.anlz",
            beat_grid=sample_beatgrid.to_model(),
            phrases=[],
        )
        strategy = CueStrategy()
        proposal = strategy.propose(track)

        assert proposal.confidence["G"] == 0.0
        assert proposal.confidence["H"] == 0.0


class TestBeatgridSnapping:
    def test_first_beat_hot_cue_at_beat_one(self, sample_track: Track, sample_beatgrid: BeatGrid):
        strategy = CueStrategy()
        proposal = strategy.propose(sample_track)

        first_beat_cue = next(c for c in proposal.hot_cues if c.comment == "First Beat")
        assert first_beat_cue.position_ms == pytest.approx(sample_beatgrid.beat_to_ms(1))

    def test_loop_in_matches_first_beat_position(self, sample_track: Track):
        strategy = CueStrategy()
        proposal = strategy.propose(sample_track)

        first_beat_cue = next(c for c in proposal.hot_cues if c.comment == "First Beat")
        loop_in_cue = next(c for c in proposal.hot_cues if c.comment == "Loop In")
        assert loop_in_cue.position_ms == pytest.approx(first_beat_cue.position_ms)
        assert loop_in_cue.is_loop

    def test_loop_end_offset_matches_config(self, sample_track: Track, sample_beatgrid: BeatGrid):
        config = CueStrategyConfig(loop_length_bars=4)
        strategy = CueStrategy(config=config)
        proposal = strategy.propose(sample_track)

        loop_in_cue = next(c for c in proposal.hot_cues if c.comment == "Loop In")
        expected_end = loop_in_cue.position_ms + sample_beatgrid.bars_to_ms(4)
        assert loop_in_cue.loop_end_ms == pytest.approx(expected_end)


class TestMemoryCueOffsets:
    def test_first_beat_memory_cue_zero_offset(self, sample_track: Track):
        strategy = CueStrategy()
        proposal = strategy.propose(sample_track)

        hot_first_beat = next(c for c in proposal.hot_cues if c.comment == "First Beat")
        mem_first_beat = next(c for c in proposal.memory_cues if c.comment == "First Beat")
        assert mem_first_beat.position_ms == pytest.approx(hot_first_beat.position_ms)

    def test_drop_memory_cue_offset_by_configured_bars(self, sample_track: Track, sample_beatgrid: BeatGrid):
        config = CueStrategyConfig(memory_offset_bars=16)
        strategy = CueStrategy(config=config)
        proposal = strategy.propose(sample_track)

        hot_drop = next(c for c in proposal.hot_cues if c.comment == "Drop")
        mem_drop = next(c for c in proposal.memory_cues if c.comment == "Drop")

        # Memory cue should be before the hot cue and snapped to a bar boundary
        assert mem_drop.position_ms < hot_drop.position_ms
        beat = sample_beatgrid.ms_to_beat(mem_drop.position_ms)
        assert (beat - 1) % 4 == 0

    def test_memory_cue_offset_clamped_to_first_beat(self, sample_beatgrid: BeatGrid):
        # Drop very close to the start of the track — offset would go negative.
        from rekordbox_mcp.domain.models import Phrase

        phrases = [
            Phrase(
                beat_start=1,
                beat_end=5,
                kind=1,
                label="Chorus",
                position_ms=sample_beatgrid.beat_to_ms(1),
                duration_ms=sample_beatgrid.bars_to_ms(1),
                mood=1,
            ),
            Phrase(
                beat_start=5,
                beat_end=100,
                kind=1,
                label="Outro",
                position_ms=sample_beatgrid.beat_to_ms(5),
                duration_ms=sample_beatgrid.bars_to_ms(20),
                mood=1,
            ),
        ]
        track = Track(
            id=5,
            title="Short Intro",
            artist="X",
            bpm=sample_beatgrid.bpm,
            duration_ms=sample_beatgrid.beat_to_ms(100) + 1000,
            analysis_path="/mock/x.anlz",
            beat_grid=sample_beatgrid.to_model(),
            phrases=phrases,
        )
        config = CueStrategyConfig(memory_offset_bars=16)
        strategy = CueStrategy(config=config)
        proposal = strategy.propose(track)

        mem_drop = next(c for c in proposal.memory_cues if c.comment == "Drop")
        assert mem_drop.position_ms == pytest.approx(sample_beatgrid.beat_to_ms(1))


class TestCreateCueStrategy:
    def test_factory_creates_strategy_with_config(self):
        strategy = create_cue_strategy(memory_offset_bars=8, loop_length_bars=2)
        assert isinstance(strategy, CueStrategy)
        assert strategy.config.memory_offset_bars == 8
        assert strategy.config.loop_length_bars == 2
        assert isinstance(strategy.profile, CueProfile)
