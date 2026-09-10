import math
from typing import Any, Iterable


class SetTimingError(ValueError):
    pass


def _finite(value: Any, name: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise SetTimingError(f"{name} は数値で指定してください") from exc
    if not math.isfinite(number):
        raise SetTimingError(f"{name} は有限の数値で指定してください")
    return number


def entry_duration_ms(entry: Any) -> float | None:
    """Return planned real duration for one set entry, or None when unknowable."""
    duration_seconds = getattr(entry, "duration", None) if not isinstance(entry, dict) else entry.get("duration")
    in_ms = _finite(getattr(entry, "in_ms", 0) if not isinstance(entry, dict) else entry.get("in_ms", 0), "IN")
    out_value = getattr(entry, "out_ms", None) if not isinstance(entry, dict) else entry.get("out_ms")
    if out_value is None:
        if duration_seconds is None:
            return None
        out_ms = _finite(duration_seconds, "曲の長さ") * 1000
    else:
        out_ms = _finite(out_value, "OUT")
    rate = _finite(getattr(entry, "playback_rate", 1) if not isinstance(entry, dict) else entry.get("playback_rate", 1), "再生速度")
    extra = _finite(getattr(entry, "extra_duration_ms", 0) if not isinstance(entry, dict) else entry.get("extra_duration_ms", 0), "追加時間")
    if in_ms < 0 or out_ms <= in_ms or rate <= 0 or extra < 0:
        raise SetTimingError("IN/OUT・再生速度・追加時間の値が不正です")
    if duration_seconds is not None and out_ms > float(duration_seconds) * 1000 + 0.5:
        raise SetTimingError("OUT が曲の長さを超えています")
    return (out_ms - in_ms) / rate + extra


def calculate_set_duration(entries: Iterable[Any]) -> dict[str, Any]:
    rows = list(entries)
    durations = [entry_duration_ms(row) for row in rows]
    total = sum(value for value in durations if value is not None)
    for index, row in enumerate(rows[:-1]):
        overlap = _finite(getattr(row, "overlap_next_ms", 0) if not isinstance(row, dict) else row.get("overlap_next_ms", 0), "重なり")
        if overlap < 0:
            raise SetTimingError("重なりは0以上で指定してください")
        left, right = durations[index], durations[index + 1]
        if overlap and (left is None or right is None or overlap > min(left, right) + 0.5):
            raise SetTimingError("重なりが隣接する曲の予定時間を超えています")
        total -= overlap
    return {
        "planned_duration_ms": total,
        "unknown_entries": sum(value is None for value in durations),
        "entry_duration_ms": durations,
    }
