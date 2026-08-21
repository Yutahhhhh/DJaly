"""PSSI Phrase analysis domain logic."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from rekordbox_mcp.domain.models import Mood, Phrase, PhraseLabel


# PSSI mood -> kind -> label mapping (from djcues)
MOOD_PHRASE_MAP: dict[int, dict[int, str]] = {
    1: {  # High
        1: "Intro",
        2: "Up",
        3: "Down",
        5: "Chorus",
        6: "Outro",
    },
    2: {  # Mid
        1: "Intro",
        2: "Verse1",
        3: "Verse2",
        4: "Verse3",
        5: "Verse4",
        6: "Verse5",
        7: "Verse6",
        8: "Bridge",
        9: "Chorus",
        10: "Outro",
    },
    3: {  # Low
        1: "Intro",
        2: "Verse1",
        3: "Verse1",
        4: "Verse1",
        5: "Verse2",
        6: "Verse2",
        7: "Verse2",
        8: "Bridge",
        9: "Chorus",
        10: "Outro",
    },
}

MOOD_NAMES: dict[int, str] = {1: "High", 2: "Mid", 3: "Low"}


def resolve_phrase_label(mood: int, kind: int) -> str:
    """Resolve a PSSI phrase kind to a human-readable label given the mood."""
    return MOOD_PHRASE_MAP.get(mood, {}).get(kind, "Unknown")


@dataclass
class PhraseAnalysisResult:
    """Result of PSSI phrase analysis."""

    phrases: list[Phrase]
    mood: int
    mood_name: str
    total_phrases: int
    track_duration_ms: float


def analyze_phrases_from_anlz(
    anlz_data: dict,
    beat_grid: "BeatGrid",
    track_duration_ms: float,
) -> PhraseAnalysisResult:
    """
    Analyze phrases from ANLZ data.

    Args:
        anlz_data: Parsed ANLZ data containing PSSI information
        beat_grid: BeatGrid for time conversions
        track_duration_ms: Total track duration in milliseconds

    Returns:
        PhraseAnalysisResult with resolved phrases
    """
    # Extract PSSI data from ANLZ
    # ANLZ structure varies, but typically contains:
    # - pssi: list of {position, kind, mood} or similar
    # - or song_structure: list of phrases

    phrases: list[Phrase] = []
    mood = 2  # Default to Mid

    # Try to extract PSSI data from various possible ANLZ structures
    pssi_data = None

    if "pssi" in anlz_data:
        pssi_data = anlz_data["pssi"]
    elif "song_structure" in anlz_data:
        pssi_data = anlz_data["song_structure"]
    elif "phrases" in anlz_data:
        pssi_data = anlz_data["phrases"]

    if pssi_data and isinstance(pssi_data, list):
        # Extract mood from first entry if available
        if pssi_data and "mood" in pssi_data[0]:
            mood = pssi_data[0].get("mood", 2)

        # Process each phrase entry
        for i, entry in enumerate(pssi_data):
            # Position can be in beats or milliseconds
            position = entry.get("position", entry.get("start", 0))
            kind = entry.get("kind", entry.get("type", 1))

            # Convert position to milliseconds if needed
            if position < 10000:  # Likely in beats
                position_ms = beat_grid.beat_to_ms(int(position))
            else:
                position_ms = float(position)

            # Determine end position (next phrase start or track end)
            if i + 1 < len(pssi_data):
                next_pos = pssi_data[i + 1].get("position", pssi_data[i + 1].get("start", 0))
                if next_pos < 10000:
                    next_pos_ms = beat_grid.beat_to_ms(int(next_pos))
                else:
                    next_pos_ms = float(next_pos)
            else:
                next_pos_ms = track_duration_ms

            duration_ms = max(0, next_pos_ms - position_ms)

            # Resolve label
            label = resolve_phrase_label(mood, kind)

            # Calculate beat positions
            beat_start = beat_grid.ms_to_beat(position_ms)
            beat_end = beat_grid.ms_to_beat(next_pos_ms)

            phrase = Phrase(
                beat_start=beat_start,
                beat_end=beat_end,
                kind=kind,
                label=label,
                position_ms=position_ms,
                duration_ms=duration_ms,
                mood=mood,
            )
            phrases.append(phrase)

    # If no phrases found, create a basic structure
    if not phrases:
        # Create default phrases based on track duration
        phrases = create_default_phrases(beat_grid, track_duration_ms, mood)

    return PhraseAnalysisResult(
        phrases=phrases,
        mood=mood,
        mood_name=MOOD_NAMES.get(mood, "Unknown"),
        total_phrases=len(phrases),
        track_duration_ms=track_duration_ms,
    )


def create_default_phrases(
    beat_grid: "BeatGrid", track_duration_ms: float, mood: int = 2
) -> list[Phrase]:
    """Create default phrase structure when PSSI data is unavailable."""
    phrases: list[Phrase] = []
    total_beats = beat_grid.ms_to_beat(track_duration_ms)

    # Typical structure: Intro (16-32 beats) -> Verse/Up -> Chorus -> etc.
    # This is a simplified heuristic
    structure = [
        ("Intro", 16),
        ("Up", 32),
        ("Chorus", 32),
        ("Down", 16),
        ("Up", 32),
        ("Chorus", 32),
        ("Bridge", 16),
        ("Chorus", 32),
        ("Outro", 16),
    ]

    current_beat = 1
    for label, length in structure:
        if current_beat >= total_beats:
            break

        end_beat = min(current_beat + length, total_beats)
        position_ms = beat_grid.beat_to_ms(current_beat)
        end_ms = beat_grid.beat_to_ms(end_beat)

        # Find matching kind for this label and mood
        kind = 1
        for k, l in MOOD_PHRASE_MAP.get(mood, {}).items():
            if l == label:
                kind = k
                break

        phrase = Phrase(
            beat_start=current_beat,
            beat_end=end_beat,
            kind=kind,
            label=label,
            position_ms=position_ms,
            duration_ms=end_ms - position_ms,
            mood=mood,
        )
        phrases.append(phrase)
        current_beat = end_beat

    return phrases


def find_phrases_by_label(
    phrases: list[Phrase], labels: list[str]
) -> list[Phrase]:
    """Find phrases matching any of the given labels."""
    return [p for p in phrases if p.label in labels]


def find_phrases_after(
    phrases: list[Phrase], position_ms: float
) -> list[Phrase]:
    """Find phrases starting after the given position."""
    return [p for p in phrases if p.position_ms > position_ms]


def find_phrases_before(
    phrases: list[Phrase], position_ms: float
) -> list[Phrase]:
    """Find phrases starting before the given position."""
    return [p for p in phrases if p.position_ms < position_ms]


def get_phrase_at_position(
    phrases: list[Phrase], position_ms: float
) -> Phrase | None:
    """Get the phrase containing the given position."""
    for phrase in phrases:
        if phrase.position_ms <= position_ms < phrase.position_ms + phrase.duration_ms:
            return phrase
    return None


def get_nearest_phrase(
    phrases: list[Phrase], position_ms: float
) -> Phrase | None:
    """Get the phrase nearest to the given position."""
    if not phrases:
        return None
    return min(phrases, key=lambda p: abs(p.position_ms - position_ms))