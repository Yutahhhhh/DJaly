"""Cue generation strategy - maps PSSI phrases and vocal detection to cue points."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from rekordbox_mcp.domain.models import (
    BeatGrid,
    CuePoint,
    CueProfile,
    CueProposal,
    CueSlotConfig,
    Phrase,
    Track,
    WaveformPoint,
)
from rekordbox_mcp.domain.vocal import VocalRegion, analyze_vocal_track, find_vocal_onset_before

_REGISTERED_PROFILES: dict[str, CueProfile] = {}


def register_cue_profile(profile: CueProfile) -> None:
    """Register a profile by name for subsequent strategy creation."""
    _REGISTERED_PROFILES[profile.name] = profile


@dataclass
class CueStrategyConfig:
    """Configuration for cue generation strategy."""

    memory_offset_bars: int = 16
    loop_length_bars: int = 4
    min_vocal_confidence: int = 3
    min_vocal_duration_ms: float = 2000.0
    min_loop_energy: float = 0.05
    min_loop_similarity: float = 0.7
    loop_bar_sizes: tuple[int, ...] = (8, 4, 2, 1)


class CueStrategy:
    """Proposes cue placements based on phrase analysis and the cue system."""

    def __init__(
        self,
        profile: CueProfile | None = None,
        config: CueStrategyConfig | None = None,
    ) -> None:
        self.profile = profile or CueProfile.default()
        self.config = config or CueStrategyConfig()

    def propose(self, track: Track) -> CueProposal:
        """Generate a cue proposal for a track based on its phrase structure."""
        if not track.beat_grid:
            raise ValueError("Track must have beat grid for cue generation")

        bg = track.beat_grid
        phrases = track.phrases
        hot_cues: list[CuePoint] = []
        memory_cues: list[CuePoint] = []
        confidence: dict[str, float] = {}
        notes: list[str] = []

        # Build positions dict keyed by pad letter
        positions: dict[str, float] = {}

        # --- A: First Beat ---
        positions["A"] = bg.beat_to_ms(1)
        confidence["A"] = 1.0
        notes.append("A (First Beat): beat 1")

        # --- B: Loop In (same as First Beat) ---
        positions["B"] = positions["A"]
        confidence["B"] = 0.6
        notes.append("B (Loop In): same position as First Beat")

        # --- D: Drop (first Chorus or Up after ~25% of track) ---
        choruses = [p for p in phrases if p.label == "Chorus"]
        drop_candidates = [p for p in phrases if p.label in ("Chorus", "Up")]
        min_drop_ms = track.duration_ms * 0.20

        if choruses:
            late_choruses = [c for c in choruses if c.position_ms >= min_drop_ms]
            if late_choruses:
                drop_phrase = late_choruses[0]
                notes.append(f"D (Drop): first Chorus after 20% at beat {drop_phrase.beat_start}")
            else:
                last_early_chorus = choruses[-1]
                ups_after = [
                    p for p in phrases
                    if p.label == "Up" and p.position_ms > last_early_chorus.position_ms
                ]
                if ups_after:
                    drop_phrase = ups_after[0]
                    notes.append(
                        f"D (Drop): Up after early Chorus, beat {drop_phrase.beat_start}"
                    )
                else:
                    drop_phrase = choruses[-1]
                    notes.append(f"D (Drop): last Chorus at beat {drop_phrase.beat_start}")
            positions["D"] = drop_phrase.position_ms
            confidence["D"] = 0.85
        else:
            notes.append("D (Drop): no Chorus found — skipped")
            confidence["D"] = 0.0

        # --- C: Vocal / Buildup ---
        vocal_placed = False
        c_drop_ms = positions.get("D", track.duration_ms)

        if track.vocal_track:
            vt_result = analyze_vocal_track(
                track.vocal_track,
                min_confidence=self.config.min_vocal_confidence,
                min_duration_ms=self.config.min_vocal_duration_ms,
            )

            for region in vt_result.regions:
                if region.start_ms < c_drop_ms:
                    # Snap to nearest phrase boundary
                    best_phrase = None
                    best_dist = float("inf")
                    for p in phrases:
                        dist = abs(p.position_ms - region.start_ms)
                        if dist < best_dist:
                            best_dist = dist
                            best_phrase = p

                    if best_phrase and best_dist < bg.bars_to_ms(4):
                        positions["C"] = best_phrase.position_ms
                        confidence["C"] = 0.85
                        notes.append(
                            f"C (Vocal/Buildup): vocal at {region.start_ms / 1000:.1f}s, "
                            f"snapped to {best_phrase.label} beat {best_phrase.beat_start}"
                        )
                    else:
                        snap_beat = bg.ms_to_beat(region.start_ms)
                        bar_beat = ((snap_beat - 1) // 4) * 4 + 1
                        positions["C"] = bg.beat_to_ms(bar_beat)
                        confidence["C"] = 0.8
                        notes.append(
                            f"C (Vocal/Buildup): vocal at {region.start_ms / 1000:.1f}s, "
                            f"snapped to beat {bar_beat}"
                        )
                    vocal_placed = True
                    break

        if not vocal_placed:
            if "D" in positions:
                ups_before = [
                    p for p in phrases
                    if p.label in ("Up", "Verse1", "Verse2", "Verse3", "Verse4", "Verse5", "Verse6")
                    and p.position_ms < c_drop_ms
                ]
                if ups_before:
                    vocal_phrase = ups_before[-1]
                    positions["C"] = vocal_phrase.position_ms
                    confidence["C"] = 0.5
                    notes.append(f"C (Vocal/Buildup): no vocal data, {vocal_phrase.label} at beat {vocal_phrase.beat_start}")
                else:
                    before_drop = [p for p in phrases if p.position_ms < c_drop_ms]
                    if before_drop:
                        fallback = before_drop[-1]
                        positions["C"] = fallback.position_ms
                        confidence["C"] = 0.3
                        notes.append(f"C (Vocal/Buildup): fallback to {fallback.label} at beat {fallback.beat_start}")
                    else:
                        confidence["C"] = 0.0
                        notes.append("C (Vocal/Buildup): no phrase found before Drop")
            else:
                ups = [p for p in phrases if p.label in ("Up", "Verse1", "Verse2")]
                if ups:
                    positions["C"] = ups[0].position_ms
                    confidence["C"] = 0.3
                    notes.append(f"C (Vocal/Buildup): no Drop, using first Up at beat {ups[0].beat_start}")
                else:
                    confidence["C"] = 0.0
                    notes.append("C (Vocal/Buildup): no suitable phrase found")

        # --- E: Breakdown (first Down/Bridge after Drop) ---
        if "D" in positions:
            drop_ms = positions["D"]
            downs_after = [p for p in phrases if p.label in ("Down", "Bridge") and p.position_ms > drop_ms]
            if downs_after:
                breakdown_phrase = downs_after[0]
                positions["E"] = breakdown_phrase.position_ms
                confidence["E"] = 0.85
                notes.append(f"E (Breakdown): {breakdown_phrase.label} at beat {breakdown_phrase.beat_start}")
            else:
                confidence["E"] = 0.0
                notes.append("E (Breakdown): no Down/Bridge found after Drop")
        else:
            downs = [p for p in phrases if p.label in ("Down", "Bridge")]
            if downs:
                positions["E"] = downs[0].position_ms
                confidence["E"] = 0.3
                notes.append(f"E (Breakdown): no Drop, using first Down at beat {downs[0].beat_start}")
            else:
                confidence["E"] = 0.0
                notes.append("E (Breakdown): no Down/Bridge found")

        # --- F: Special / Second Drop ---
        f_placed = False
        if "D" in positions and track.waveform and phrases:
            drop_ms = positions["D"]
            n_wf = len(track.waveform)

            # Compute per-phrase energy
            phrase_energy: list[tuple[Phrase, float]] = []
            for p in phrases:
                i0 = int(n_wf * p.position_ms / track.duration_ms)
                i1 = int(n_wf * (p.position_ms + p.duration_ms) / track.duration_ms)
                if i1 > i0:
                    heights = [pt.height for pt in track.waveform[i0:i1]]
                    phrase_energy.append((p, sum(heights) / len(heights)))
                else:
                    phrase_energy.append((p, 0.0))

            peak_energy = max((e for _, e in phrase_energy), default=0)
            if peak_energy > 0:
                dip_threshold = peak_energy * 0.75
                recovery_threshold = peak_energy * 0.85

                recoveries: list[Phrase] = []
                dip_found = False
                for p, energy in phrase_energy:
                    if p.position_ms <= drop_ms:
                        continue
                    if energy < dip_threshold:
                        dip_found = True
                    elif dip_found and energy >= recovery_threshold:
                        recoveries.append(p)
                        dip_found = False

                if recoveries:
                    pick = recoveries[1] if len(recoveries) >= 2 else recoveries[0]
                    positions["F"] = pick.position_ms
                    confidence["F"] = 0.75
                    notes.append(
                        f"F (Special): energy recovery #{min(2, len(recoveries))}"
                        f"/{len(recoveries)} at {pick.label} beat {pick.beat_start}"
                    )
                    f_placed = True

        if not f_placed:
            if "E" in positions:
                breakdown_ms = positions["E"]
                choruses_after = [p for p in phrases if p.label == "Chorus" and p.position_ms > breakdown_ms]
                if choruses_after:
                    positions["F"] = choruses_after[0].position_ms
                    confidence["F"] = 0.5
                    notes.append(f"F (Special): fallback Chorus at beat {choruses_after[0].beat_start}")
                else:
                    confidence["F"] = 0.0
                    notes.append("F (Special): no Chorus found after Breakdown")
            elif "D" in positions:
                drop_ms = positions["D"]
                later_choruses = [p for p in phrases if p.label == "Chorus" and p.position_ms > drop_ms]
                if later_choruses:
                    positions["F"] = later_choruses[0].position_ms
                    confidence["F"] = 0.5
                    notes.append(f"F (Special): fallback Chorus at beat {later_choruses[0].beat_start}")
                else:
                    confidence["F"] = 0.0
                    notes.append("F (Special): no later Chorus found")
            else:
                confidence["F"] = 0.0
                notes.append("F (Special): no Drop or Breakdown to anchor from")

        # --- G: Outro ---
        outros = [p for p in phrases if p.label == "Outro"]
        if outros:
            positions["G"] = outros[0].position_ms
            confidence["G"] = 0.9
            notes.append(f"G (Outro): Outro at beat {outros[0].beat_start}")
        elif phrases:
            positions["G"] = phrases[-1].position_ms
            confidence["G"] = 0.4
            notes.append(f"G (Outro): no Outro found, using last phrase at beat {phrases[-1].beat_start}")
        else:
            confidence["G"] = 0.0
            notes.append("G (Outro): no phrases at all")

        # --- H: Loop Out (same as Outro) ---
        if "G" in positions:
            positions["H"] = positions["G"]
            confidence["H"] = 0.4
            notes.append("H (Loop Out): same position as Outro")
        else:
            confidence["H"] = 0.0
            notes.append("H (Loop Out): no Outro to anchor from")

        # --- Build CuePoint objects ---
        for slot in self.profile.slots:
            pad = slot.pad
            if pad not in positions:
                continue

            pos_ms = positions[pad]
            loop_end = None
            if slot.is_loop:
                loop_end = pos_ms + bg.bars_to_ms(self.config.loop_length_bars)

            hot_cues.append(CuePoint(
                track_id=track.id,
                kind=slot.kind,
                position_ms=pos_ms,
                loop_end_ms=loop_end,
                color_table_index=slot.hot_cue_color_table_index,
                color=slot.hot_cue_color,
                comment=slot.hot_cue_label,
            ))

            # Memory cue
            if slot.memory_offset_bars == 0:
                mem_pos = pos_ms
            else:
                mem_pos = pos_ms - bg.bars_to_ms(slot.memory_offset_bars)
                first_beat_ms = bg.beat_to_ms(1)
                if mem_pos < first_beat_ms:
                    mem_pos = first_beat_ms
                else:
                    mem_beat = bg.ms_to_beat(mem_pos)
                    bar_beat = ((mem_beat - 1) // 4) * 4 + 1
                    mem_pos = bg.beat_to_ms(bar_beat)

            mem_loop_end = None
            if slot.is_loop:
                mem_loop_end = mem_pos + bg.bars_to_ms(self.config.loop_length_bars)

            memory_cues.append(CuePoint(
                track_id=track.id,
                kind=0,
                position_ms=mem_pos,
                loop_end_ms=mem_loop_end,
                color_table_index=slot.memory_cue_color_table_index,
                color=slot.memory_cue_color,
                comment=slot.memory_cue_label,
            ))

        return CueProposal(
            track_id=track.id,
            hot_cues=hot_cues,
            memory_cues=memory_cues,
            confidence=confidence,
            notes=notes,
        )

    def _spectral_similarity(
        self,
        wf_points: list[WaveformPoint],
        i0: int,
        i_mid: int,
        i1: int,
    ) -> float:
        """Compare the RGB profile of two halves of a waveform section."""
        half_len = min(i_mid - i0, i1 - i_mid)
        if half_len < 2:
            return 0.0

        first_half = wf_points[i0 : i0 + half_len]
        second_half = wf_points[i_mid : i_mid + half_len]

        total_mse = 0.0
        for a, b in zip(first_half, second_half):
            dr = (a.red - b.red) / 7
            dg = (a.green - b.green) / 7
            db = (a.blue - b.blue) / 7
            dh = a.height - b.height
            total_mse += dr * dr + dg * dg + db * db + dh * dh

        mse = total_mse / half_len / 4
        return max(0.0, 1.0 - mse)

    def _find_stable_loop(
        self,
        track: Track,
        search_start_ms: float,
        search_end_ms: float,
    ) -> tuple[float, int, float] | None:
        """Find a stable, loopable region using waveform energy and spectral similarity."""
        if not track.waveform or not track.beat_grid:
            return None

        bg = track.beat_grid
        n = len(track.waveform)
        total_ms = track.duration_ms

        for loop_bars in self.config.loop_bar_sizes:
            loop_ms = bg.bars_to_ms(loop_bars)
            best_pos = None
            best_score = 0.0

            start_beat = bg.ms_to_beat(search_start_ms)
            bar_start = ((start_beat - 1) // 4) * 4 + 1
            pos_ms = bg.beat_to_ms(bar_start)

            while pos_ms + loop_ms <= search_end_ms and pos_ms + loop_ms <= total_ms:
                i0 = int(n * pos_ms / total_ms)
                i1 = int(n * (pos_ms + loop_ms) / total_ms)
                i_mid = (i0 + i1) // 2
                if i1 - i0 < 4:
                    pos_ms += bg.bars_to_ms(1)
                    continue

                heights = [p.height for p in track.waveform[i0:i1]]
                mean_e = sum(heights) / len(heights)
                if mean_e < self.config.min_loop_energy:
                    pos_ms += bg.bars_to_ms(1)
                    continue

                similarity = self._spectral_similarity(track.waveform, i0, i_mid, i1)
                if similarity > best_score:
                    best_score = similarity
                    best_pos = pos_ms

                pos_ms += bg.bars_to_ms(1)

            if best_pos is not None and best_score >= self.config.min_loop_similarity:
                return (best_pos, loop_bars, best_score)

        return None


def create_cue_strategy(
    profile_name: str = "default",
    memory_offset_bars: int = 16,
    loop_length_bars: int = 4,
) -> CueStrategy:
    """Factory function to create a CueStrategy with common settings."""
    if profile_name == "default":
        profile = CueProfile.default()
    elif profile_name.lower().endswith(".csv"):
        profile = CueProfile.from_csv(profile_name)
        register_cue_profile(profile)
    elif profile_name in _REGISTERED_PROFILES:
        profile = _REGISTERED_PROFILES[profile_name]
    else:
        # Named profiles are conventionally stored here.  Loading them also
        # registers them, so later calls can use the short profile name.
        candidates = [Path("~/.rekordbox-mcp/profiles").expanduser() / f"{profile_name}.csv"]
        profile_path = next((path for path in candidates if path.is_file()), None)
        if profile_path is None:
            profile = CueProfile.default()
        else:
            profile = CueProfile.from_csv(profile_path)
            register_cue_profile(profile)
    config = CueStrategyConfig(
        memory_offset_bars=memory_offset_bars,
        loop_length_bars=loop_length_bars,
    )
    return CueStrategy(profile=profile, config=config)
