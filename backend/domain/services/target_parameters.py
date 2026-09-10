"""Validation helpers for model-selected audio-feature targets.

Natural-language interpretation belongs to the MCP client. plumdeck only accepts
the resulting structured values and applies them to deterministic search and
setlist algorithms.
"""

from typing import Any, Dict, Optional


FEATURE_RANGES = {
    "energy": (0.0, 1.0),
    "danceability": (0.0, 1.0),
    "brightness": (0.0, 1.0),
    "noisiness": (0.0, 1.0),
}


def sanitize_target_parameters(values: Optional[Dict[str, Any]]) -> Dict[str, float]:
    """Return finite, clamped numeric targets supported by plumdeck."""
    if not values or not isinstance(values, dict):
        return {}

    result: Dict[str, float] = {}
    for key, value in values.items():
        if isinstance(value, bool) or value is None:
            continue
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if number != number or number in (float("inf"), float("-inf")):
            continue

        if key == "bpm":
            result[key] = max(1.0, min(300.0, number))
        elif key in FEATURE_RANGES:
            lower, upper = FEATURE_RANGES[key]
            result[key] = max(lower, min(upper, number))
        elif key in ("year_min", "year_max"):
            result[key] = float(max(1900, min(2100, int(number))))

    if (
        "year_min" in result
        and "year_max" in result
        and result["year_min"] > result["year_max"]
    ):
        result["year_min"], result["year_max"] = (
            result["year_max"],
            result["year_min"],
        )
    return result


def build_target_parameters(
    *,
    bpm: Optional[float] = None,
    energy: Optional[float] = None,
    danceability: Optional[float] = None,
    brightness: Optional[float] = None,
    noisiness: Optional[float] = None,
    year_min: Optional[int] = None,
    year_max: Optional[int] = None,
) -> Dict[str, float]:
    return sanitize_target_parameters(
        {
            "bpm": bpm,
            "energy": energy,
            "danceability": danceability,
            "brightness": brightness,
            "noisiness": noisiness,
            "year_min": year_min,
            "year_max": year_max,
        }
    )
