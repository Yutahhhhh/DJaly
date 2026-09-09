"""Scoring for assist-mode "what should I play next" suggestions.

The three intents ask genuinely different questions, so they weight the same
measurements differently rather than reordering one fixed score:

* ``groove``   — stay in the current pocket: tempo and feel continuity dominate.
* ``shift``    — deliberately change the room: contrast is rewarded, but the
                 transition still has to be mixable.
* ``wordplay`` — only tracks with a human-approved wordplay edge out of the
                 source, ranked by how playable that transition is.

A component whose inputs are missing is dropped and the remaining weights are
renormalized. Substituting a neutral value would quietly turn "we do not know"
into "this is fine", which is exactly the failure a DJ cannot afford mid-set.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Any, Iterable, Optional

from utils.audio_math import CAMELOT_ADJACENCY, bpm_distance, normalize_key

INTENTS = ("groove", "shift", "wordplay")
ENERGY_DIRECTIONS = ("up", "hold", "down")

INTENT_WEIGHTS: dict[str, dict[str, float]] = {
    "groove": {"bpm": 0.34, "key": 0.20, "vector": 0.16, "feature": 0.16, "energy": 0.14},
    "shift": {"bpm": 0.24, "key": 0.22, "vector": 0.08, "contrast": 0.28, "energy": 0.18},
    "wordplay": {"wordplay": 0.40, "bpm": 0.24, "key": 0.18, "vector": 0.08, "energy": 0.10},
}

# Feel features compared between two tracks. Deliberately excludes brightness,
# which tracks mastering more than performance feel.
FEEL_FEATURES = ("energy", "danceability", "noisiness")

# groove keeps the floor: beyond ±6% the blend stops being a continuation.
GROOVE_MAX_TEMPO_DISTANCE = math.log2(1.06)
# How far "up"/"down" is asking the energy to move.
ENERGY_STEP = 0.15

@dataclass
class Reason:
    kind: str
    tone: str  # "good" | "neutral" | "caution"
    text: str

    def to_dict(self) -> dict[str, str]:
        return {"kind": self.kind, "tone": self.tone, "text": self.text}


@dataclass
class Scored:
    score: float
    components: dict[str, float] = field(default_factory=dict)
    reasons: list[Reason] = field(default_factory=list)


def _number(value: Any) -> Optional[float]:
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _positive(value: Any) -> Optional[float]:
    number = _number(value)
    return number if number is not None and number > 0 else None


def tempo_score(source_bpm: Any, candidate_bpm: Any) -> Optional[float]:
    """Gaussian around the nearest half/double-time interpretation."""
    if _positive(source_bpm) is None or _positive(candidate_bpm) is None:
        return None
    distance = bpm_distance(float(source_bpm), float(candidate_bpm))
    if not math.isfinite(distance):
        return None
    return math.exp(-0.5 * (distance / math.log2(1.08)) ** 2)


def key_score(source_key: Any, candidate_key: Any) -> Optional[float]:
    """Camelot compatibility. Unknown on either side means unknown, not 0.5."""
    source = normalize_key(source_key if isinstance(source_key, str) else None)
    candidate = normalize_key(candidate_key if isinstance(candidate_key, str) else None)
    if not source or not candidate:
        return None
    if source == candidate:
        return 1.0
    return 0.9 if candidate in CAMELOT_ADJACENCY.get(source, []) else 0.15


def _feature_deltas(source: dict, candidate: dict) -> dict[str, float]:
    deltas = {}
    for feature in FEEL_FEATURES:
        left, right = _number(source.get(feature)), _number(candidate.get(feature))
        if left is not None and right is not None:
            deltas[feature] = right - left
    return deltas


def feature_closeness(source: dict, candidate: dict) -> Optional[float]:
    deltas = _feature_deltas(source, candidate)
    if not deltas:
        return None
    mean_delta = sum(abs(value) for value in deltas.values()) / len(deltas)
    return max(0.0, 1.0 - min(1.0, mean_delta / 0.35))


def energy_alignment(source: dict, candidate: dict, direction: str) -> Optional[float]:
    left, right = _number(source.get("energy")), _number(candidate.get("energy"))
    if left is None or right is None:
        return None
    delta = right - left
    if direction == "hold":
        return max(0.0, 1.0 - min(1.0, abs(delta) / (ENERGY_STEP * 2)))
    signed = delta if direction == "up" else -delta
    return min(1.0, max(0.0, 0.5 + signed / (ENERGY_STEP * 2)))


def contrast_score(source: dict, candidate: dict) -> Optional[float]:
    """How much the candidate actually changes the room.

    Feel distance plus a genre change; a "shift" that keeps every measurable
    property identical is not a shift.
    """
    closeness = feature_closeness(source, candidate)
    genre_changed = _genre_changed(source, candidate)
    if closeness is None and genre_changed is None:
        return None
    parts = []
    if closeness is not None:
        parts.append(1.0 - closeness)
    if genre_changed is not None:
        parts.append(1.0 if genre_changed else 0.0)
    return sum(parts) / len(parts)


def _genre_changed(source: dict, candidate: dict) -> Optional[bool]:
    left = (source.get("genre") or "").strip().casefold()
    right = (candidate.get("genre") or "").strip().casefold()
    if not left or not right:
        return None
    return left != right


def wordplay_score(pair: Optional[dict]) -> Optional[float]:
    """Approved wordplay edges only; a tested one outranks an untested one."""
    if not pair:
        return None
    return 1.0 if pair.get("verification_status") == "tested" else 0.8


def passes_intent_filter(intent: str, source: dict, candidate: dict) -> bool:
    """Hard constraints that ranking must not be able to talk its way past."""
    if intent == "groove":
        source_bpm, candidate_bpm = _positive(source.get("bpm")), _positive(candidate.get("bpm"))
        if source_bpm is None or candidate_bpm is None:
            # Without a tempo on both sides there is no evidence the groove
            # continues, and groove is exactly the promise being made.
            return False
        return bpm_distance(source_bpm, candidate_bpm) <= GROOVE_MAX_TEMPO_DISTANCE
    return True


def evaluate(
    source: dict,
    candidate: dict,
    intent: str,
    energy_direction: str,
    vector_similarity: Optional[float] = None,
    pair: Optional[dict] = None,
    has_analysis: bool = True,
) -> Scored:
    """Scores one candidate and explains the result."""
    if intent not in INTENT_WEIGHTS:
        raise ValueError(f"unknown intent: {intent}")
    if energy_direction not in ENERGY_DIRECTIONS:
        raise ValueError(f"unknown energy direction: {energy_direction}")

    weights = INTENT_WEIGHTS[intent]
    values: dict[str, Optional[float]] = {
        "bpm": tempo_score(source.get("bpm"), candidate.get("bpm")),
        "key": key_score(source.get("key"), candidate.get("key")),
        "vector": _number(vector_similarity),
        "feature": feature_closeness(source, candidate),
        "contrast": contrast_score(source, candidate),
        "energy": energy_alignment(source, candidate, energy_direction),
        "wordplay": wordplay_score(pair),
    }

    components = {
        name: max(0.0, min(1.0, value))
        for name, value in values.items()
        if name in weights and value is not None
    }
    available = sum(weights[name] for name in components)
    score = (
        sum(weights[name] * value for name, value in components.items()) / available
        if available > 0
        else 0.0
    )
    reasons = build_reasons(
        source, candidate, intent, energy_direction, values, pair, has_analysis
    )
    return Scored(score=score, components=components, reasons=reasons)


def build_reasons(
    source: dict,
    candidate: dict,
    intent: str,
    energy_direction: str,
    values: dict[str, Optional[float]],
    pair: Optional[dict],
    has_analysis: bool,
) -> list[Reason]:
    reasons: list[Reason] = []

    # An approved edge is worth surfacing under any intent, not just wordplay.
    if pair:
        reasons.append(_wordplay_reason(pair))

    reasons.append(_tempo_reason(source, candidate))
    reasons.append(_key_reason(source, candidate, values.get("key")))
    reasons.append(_energy_reason(source, candidate, energy_direction))

    genre_reason = _genre_reason(source, candidate, intent)
    if genre_reason:
        reasons.append(genre_reason)

    similarity = values.get("vector")
    if similarity is not None:
        reasons.append(
            Reason(
                "similarity",
                "neutral",
                "音色の傾向が近い" if similarity >= 0.7 else "音色の傾向に違いがある",
            )
        )
    elif has_analysis:
        reasons.append(
            Reason("similarity", "caution", "音色を比較できません")
        )
    else:
        reasons.append(
            Reason("similarity", "caution", "音響解析が未実行です")
        )
    return reasons


def _tempo_reason(source: dict, candidate: dict) -> Reason:
    source_bpm, candidate_bpm = _positive(source.get("bpm")), _positive(candidate.get("bpm"))
    if source_bpm is None or candidate_bpm is None:
        return Reason("tempo", "caution", "BPM が未取得のためテンポの相性は判定できません")
    distance = bpm_distance(source_bpm, candidate_bpm)
    ratio = math.log2(candidate_bpm) - math.log2(source_bpm)
    shift = min((0, -1, 1), key=lambda value: abs(ratio + value))
    effective_bpm = candidate_bpm * (2 ** shift)
    percent = (effective_bpm / source_bpm - 1) * 100
    conversion = "1/2" if shift == -1 else "2倍"
    note = f"、原曲{candidate_bpm:g} BPMの{conversion}換算" if shift else ""
    tone = "good" if distance <= math.log2(1.03) else "neutral" if distance <= GROOVE_MAX_TEMPO_DISTANCE else "caution"
    return Reason(
        "tempo",
        tone,
        f"BPM {source_bpm:g} → {effective_bpm:g}（{percent:+.1f}%{note}）",
    )


def _key_reason(source: dict, candidate: dict, score: Optional[float]) -> Reason:
    left = normalize_key(source.get("key") if isinstance(source.get("key"), str) else None)
    right = normalize_key(candidate.get("key") if isinstance(candidate.get("key"), str) else None)
    if score is None:
        missing = "元曲" if not left else "候補"
        return Reason("key", "caution", f"{missing}のキー情報がないため判定できません")
    relation = "同一" if score >= 1.0 else "隣接" if score >= 0.9 else "非隣接"
    tone = "good" if score >= 0.9 else "caution"
    return Reason("key", tone, f"キー {left} → {right}：{relation}")


def _energy_reason(source: dict, candidate: dict, direction: str) -> Reason:
    left, right = _number(source.get("energy")), _number(candidate.get("energy"))
    if left is None or right is None:
        return Reason("energy", "caution", "エネルギーは未解析です")
    delta = right - left
    aligned = energy_alignment(source, candidate, direction) or 0.0
    tone = "good" if aligned >= 0.65 else "neutral" if aligned >= 0.4 else "caution"
    return Reason(
        "energy",
        tone,
        "エネルギーを維持" if abs(delta) < 0.05 else "エネルギーを上げる" if delta > 0 else "エネルギーを下げる",
    )


def _genre_reason(source: dict, candidate: dict, intent: str) -> Optional[Reason]:
    changed = _genre_changed(source, candidate)
    if changed is None:
        return None
    left = (source.get("genre") or "").strip()
    right = (candidate.get("genre") or "").strip()
    if not changed:
        tone = "good" if intent != "shift" else "caution"
        return Reason("genre", tone, f"{left} を継続")
    tone = "good" if intent == "shift" else "neutral"
    return Reason("genre", tone, f"{left} → {right} へ切り替え")


def _wordplay_reason(pair: dict) -> Reason:
    keyword = pair.get("keyword") or ""
    source_phrase = (pair.get("source_phrase") or "").strip()
    target_phrase = (pair.get("target_phrase") or "").strip()
    tested = pair.get("verification_status") == "tested"
    caveat = (
        "音出し検証済み"
        if tested
        else "音出しは未検証です（承認は音を確認したという意味ではありません）"
    )
    return Reason(
        "wordplay",
        "good" if tested else "neutral",
        f"承認済みワードプレイ「{keyword}」：「{source_phrase}」→「{target_phrase}」／{caveat}",
    )


def rank(scored: Iterable[tuple[Any, Scored]], limit: int) -> list[tuple[Any, Scored]]:
    """Deterministic ordering: score first, then track id, never insertion order."""
    ordered = sorted(scored, key=lambda item: (-item[1].score, _sort_id(item[0])))
    return ordered[: max(0, limit)]


def _sort_id(track: Any) -> int:
    identifier = track.get("id") if isinstance(track, dict) else getattr(track, "id", None)
    return int(identifier) if isinstance(identifier, int) else 0
