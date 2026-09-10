#!/usr/bin/env python3
"""Build a HOUSE path from mix-zone audio, not whole-track metadata alone."""

from __future__ import annotations

import json
import math
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

import duckdb
import numpy as np


DB_PATH = Path("/Users/horiyuuta/Library/Application Support/plumdeck/plumdeck.duckdb")
SR = 22050
SEGMENT_SECONDS = 16.0


@dataclass
class Track:
    id: int
    artist: str
    title: str
    bpm: float
    key: str
    genre: str
    subgenre: str
    energy: float
    danceability: float
    duration: float
    filepath: str
    embedding: np.ndarray
    stage: int
    rekordbox_id: int = 0
    zones: dict[str, np.ndarray] | None = None


def norm_text(value: str) -> str:
    value = re.sub(r"\([^)]*\)|\[[^]]*\]", " ", value.lower())
    return re.sub(r"[^a-z0-9]+", "", value)


def stage_for(subgenre: str, genre: str) -> int:
    value = subgenre.lower()
    if any(x in value for x in ("nu disco", "disco house", "soulful")):
        return 3
    if any(x in value for x in ("funky", "french", "filter", "classic")):
        return 2
    if any(x in value for x in ("jackin", "garage", "house music", "chicago")) or value in ("house", ""):
        return 1
    return 0


NOTE_TO_PC = {
    "c": 0, "c#": 1, "db": 1, "d": 2, "d#": 3, "eb": 3, "e": 4, "f": 5,
    "f#": 6, "gb": 6, "g": 7, "g#": 8, "ab": 8, "a": 9, "a#": 10, "bb": 10, "b": 11,
}


def parse_key(value: str) -> tuple[int, str] | None:
    match = re.match(r"^([A-Ga-g](?:#|b)?)\s*(major|minor|m)?$", value.strip())
    if not match:
        return None
    note = match.group(1).lower()
    mode_text = (match.group(2) or "major").lower()
    mode = "minor" if mode_text in ("m", "minor") else "major"
    return NOTE_TO_PC[note], mode


def key_score(source: str, target: str) -> float:
    a = parse_key(source)
    b = parse_key(target)
    if not a or not b:
        return 0.55
    apc, amode = a
    bpc, bmode = b
    if apc == bpc and amode == bmode:
        return 1.0
    if amode == bmode and ((apc - bpc) % 12 in (5, 7)):
        return 0.92
    # Relative major/minor.
    if amode == "minor" and bmode == "major" and bpc == (apc + 3) % 12:
        return 0.92
    if amode == "major" and bmode == "minor" and bpc == (apc - 3) % 12:
        return 0.92
    if apc == bpc:
        return 0.78
    return 0.0


def unit(vector: np.ndarray) -> np.ndarray:
    length = float(np.linalg.norm(vector))
    return vector / length if length else vector


def load_pcm(path: str, start: float, duration: float = SEGMENT_SECONDS) -> np.ndarray:
    command = [
        "ffmpeg", "-v", "error", "-ss", f"{max(0.0, start):.3f}", "-i", path,
        "-t", f"{duration:.3f}", "-ac", "1", "-ar", str(SR),
        "-f", "f32le", "pipe:1",
    ]
    result = subprocess.run(command, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    audio = np.frombuffer(result.stdout, dtype="<f4").astype(np.float32)
    target = int(SR * duration)
    if audio.size < target:
        audio = np.pad(audio, (0, target - audio.size))
    return audio[:target]


def cosine(a: np.ndarray, b: np.ndarray) -> float:
    denom = float(np.linalg.norm(a) * np.linalg.norm(b))
    return float(np.dot(a, b) / denom) if denom else 0.0


def autocorr_signature(envelope: np.ndarray, bins: int = 24) -> np.ndarray:
    envelope = envelope - float(np.mean(envelope))
    corr = np.correlate(envelope, envelope, mode="full")[len(envelope) - 1:]
    corr = corr[: max(bins * 4, bins)]
    if corr.size < bins:
        corr = np.pad(corr, (0, bins - corr.size))
    points = np.linspace(0, max(0, corr.size - 1), bins)
    signature = np.interp(points, np.arange(corr.size), corr)
    return unit(np.maximum(signature, 0.0).astype(np.float32))


def zone_features(audio: np.ndarray) -> np.ndarray:
    frame = 2048
    hop = 512
    if audio.size < frame:
        audio = np.pad(audio, (0, frame - audio.size))
    count = 1 + (audio.size - frame) // hop
    frames = np.lib.stride_tricks.sliding_window_view(audio, frame)[::hop][:count]
    frames = frames * np.hanning(frame).astype(np.float32)
    spectrum = np.abs(np.fft.rfft(frames, axis=1)).astype(np.float32) ** 2
    freqs = np.fft.rfftfreq(frame, 1.0 / SR)
    bands = [(25, 70), (70, 160), (160, 400), (400, 2000), (2000, 6000), (6000, 10500)]
    energies = []
    envelopes = []
    for low, high in bands:
        mask = (freqs >= low) & (freqs < high)
        env = np.log1p(np.mean(spectrum[:, mask], axis=1))
        envelopes.append(env)
        energies.append(float(np.mean(env)))
    energies_arr = np.array(energies, dtype=np.float32)
    energy_shape = unit(np.maximum(energies_arr, 0.0))
    low_env = envelopes[0] + envelopes[1]
    high_env = envelopes[4] + envelopes[5]
    low_onset = np.maximum(np.diff(low_env, prepend=low_env[0]), 0.0)
    high_onset = np.maximum(np.diff(high_env, prepend=high_env[0]), 0.0)
    kick_ac = autocorr_signature(low_onset)
    perc_ac = autocorr_signature(high_onset)
    rms_frames = np.sqrt(np.mean(frames * frames, axis=1) + 1e-12)
    rms_db = 20.0 * np.log10(np.maximum(rms_frames, 1e-8))
    centroid = np.sum(spectrum * freqs[None, :], axis=1) / np.maximum(np.sum(spectrum, axis=1), 1e-9)
    flatness = np.exp(np.mean(np.log(spectrum + 1e-12), axis=1)) / np.maximum(np.mean(spectrum, axis=1), 1e-12)
    extras = np.array([
        float(np.mean(rms_db)) / 60.0,
        float(np.std(rms_db)) / 20.0,
        float(np.mean(centroid)) / 8000.0,
        float(np.mean(flatness)),
        float(np.mean(low_onset > np.percentile(low_onset, 75))),
        float(np.mean(high_onset > np.percentile(high_onset, 75))),
        float(np.mean(envelopes[3])) / 15.0,
    ], dtype=np.float32)
    return np.concatenate([energy_shape, kick_ac, perc_ac, extras])


def analyze_track(track: Track) -> None:
    cache_dir = Path("/tmp/plumdeck_house_zone_cache")
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path = cache_dir / f"{track.id}-{int(Path(track.filepath).stat().st_mtime)}.npz"
    if cache_path.is_file():
        with np.load(cache_path) as cached:
            track.zones = {name: cached[name] for name in cached.files}
        return
    # Two phrase-sized windows at each edge. The last four seconds are avoided.
    starts = {
        "intro_a": 0.0,
        "intro_b": SEGMENT_SECONDS,
        "outro_a": max(0.0, track.duration - (SEGMENT_SECONDS * 2 + 4.0)),
        "outro_b": max(0.0, track.duration - (SEGMENT_SECONDS + 4.0)),
    }
    track.zones = {name: zone_features(load_pcm(track.filepath, start)) for name, start in starts.items()}
    np.savez_compressed(cache_path, **track.zones)


def mix_score(source: Track, target: Track) -> tuple[float, str, dict[str, float]]:
    assert source.zones and target.zones
    best: tuple[float, str, dict[str, float]] | None = None
    for source_zone in ("outro_a", "outro_b"):
        for target_zone in ("intro_a", "intro_b"):
            a = source.zones[source_zone]
            b = target.zones[target_zone]
            band = cosine(a[:6], b[:6])
            kick = cosine(a[6:30], b[6:30])
            percussion = cosine(a[30:54], b[30:54])
            loudness = max(0.0, 1.0 - abs(float(a[54] - b[54])) * 2.5)
            spectral = max(0.0, 1.0 - abs(float(a[56] - b[56])) * 3.0)
            bpm = max(0.0, 1.0 - abs(source.bpm - target.bpm) / 3.0)
            embedding = max(0.0, cosine(source.embedding, target.embedding))
            # Penalize two simultaneously dense midrange zones; this is where vocals/leads clash.
            busy_penalty = max(0.0, min(float(a[60]), float(b[60])) - 0.62) * 0.20
            score = (
                0.27 * kick + 0.24 * percussion + 0.17 * band + 0.09 * loudness
                + 0.06 * spectral + 0.10 * bpm + 0.07 * embedding - busy_penalty
            )
            details = {
                "kick": kick,
                "percussion": percussion,
                "band": band,
                "loudness": loudness,
                "spectral": spectral,
                "bpm": bpm,
                "embedding": embedding,
                "busy_penalty": busy_penalty,
            }
            item = (score, f"{source_zone}->{target_zone}", details)
            if best is None or item[0] > best[0]:
                best = item
    assert best is not None
    return best


def scan_mix_windows(source: Track, target: Track) -> list[tuple[float, float, float, dict[str, float]]]:
    """Scan usable latter/early phrase windows for a pair and return best matches."""
    source_starts = np.arange(source.duration * 0.40, max(source.duration * 0.40, source.duration - 16.0), 8.0)
    target_starts = np.arange(0.0, max(8.0, target.duration * 0.45), 8.0)
    source_features = [(float(start), zone_features(load_pcm(source.filepath, float(start)))) for start in source_starts]
    target_features = [(float(start), zone_features(load_pcm(target.filepath, float(start)))) for start in target_starts]
    results = []
    for source_start, a in source_features:
        for target_start, b in target_features:
            band = cosine(a[:6], b[:6])
            kick = cosine(a[6:30], b[6:30])
            percussion = cosine(a[30:54], b[30:54])
            loudness = max(0.0, 1.0 - abs(float(a[54] - b[54])) * 2.5)
            # Prefer windows with less midrange density to reduce vocal/lead collision.
            clean = max(0.0, 1.0 - max(float(a[60]), float(b[60])))
            score = 0.31 * kick + 0.29 * percussion + 0.18 * band + 0.10 * loudness + 0.12 * clean
            results.append((score, source_start, target_start, {
                "kick": kick, "percussion": percussion, "band": band,
                "loudness": loudness, "clean": clean,
            }))
    return sorted(results, reverse=True, key=lambda item: item[0])


def load_tracks() -> tuple[dict[int, Track], list[Track]]:
    rekordbox_rows = json.loads(Path("/tmp/plumdeck_rekordbox_meta.json").read_text(encoding="utf-8"))
    rekordbox_by_title: dict[str, list[dict]] = {}
    for item in rekordbox_rows:
        rekordbox_by_title.setdefault(norm_text(str(item.get("title") or "")), []).append(item)
    connection = duckdb.connect(str(DB_PATH), read_only=True)
    connection.execute("PRAGMA disable_progress_bar")
    rows = connection.execute(
        """
        SELECT t.id, t.artist, t.title, t.bpm, t.key, t.genre, t.subgenre,
               t.energy, t.danceability, t.duration, t.filepath, e.embedding_json
        FROM tracks t
        JOIN track_embeddings e ON e.track_id = t.id
        WHERE t.bpm BETWEEN 123 AND 129
          AND t.genre IN ('House', 'Funk')
          AND length(e.embedding_json) > 10
        """
    ).fetchall()
    tracks: dict[int, Track] = {}
    for row in rows:
        path = str(row[10])
        if not Path(path).is_file():
            continue
        vector = unit(np.asarray(json.loads(row[11]), dtype=np.float32))
        title_matches = rekordbox_by_title.get(norm_text(str(row[2] or "")), [])
        exact_artist = [
            item for item in title_matches
            if norm_text(str(item.get("artist") or "")) == norm_text(str(row[1] or ""))
        ]
        matches = exact_artist or title_matches
        if not matches:
            continue
        rekordbox = min(matches, key=lambda item: abs(float(item.get("bpm") or 0) - float(row[3] or 0)))
        track = Track(
            id=int(row[0]), artist=str(row[1] or ""), title=str(row[2] or ""),
            bpm=float(rekordbox.get("bpm") or row[3] or 0),
            key=str(rekordbox.get("key") or row[4] or ""), genre=str(row[5] or ""),
            subgenre=str(row[6] or ""), energy=float(row[7] or 0),
            danceability=float(row[8] or 0), duration=float(row[9] or 0),
            filepath=path, embedding=vector, stage=stage_for(str(row[6] or ""), str(row[5] or "")),
            rekordbox_id=int(rekordbox["id"]),
        )
        tracks[track.id] = track

    anchor_ids = [7565, 8228, 201, 3809, 3846, 7682, 7843, 6339, 8321, 6728, 8471, 7976]
    anchors = [tracks[item] for item in anchor_ids if item in tracks]
    selected: dict[int, Track] = {track.id: track for track in anchors}
    allowed = {
        "Tech House", "House", "Funky House", "Disco House", "Nu Disco", "French House",
        "Jackin House", "Jackin' House", "Filter House", "Chicago House", "Garage House",
        "Soulful House", "",
    }
    for anchor in anchors:
        ranked = sorted(
            (
                track for track in tracks.values()
                if track.subgenre in allowed
                and "radio" not in track.title.lower()
                and "short version" not in track.title.lower()
                and not track.title.lower().endswith(" - mixed")
                and "transition" not in track.title.lower()
                and bool(track.subgenre)
                and track.id not in (7976, 8471)
            ),
            key=lambda track: cosine(anchor.embedding, track.embedding), reverse=True,
        )[:28]
        selected.update({track.id: track for track in ranked})
    # Include the existing curated HOUSE journey as useful local candidates.
    journey_ids = [
        3846, 8544, 7179, 8731, 10580, 8872, 8645, 6427, 7875, 7408, 201,
        8228, 8474, 6627, 3809, 12016, 10427, 8073,
    ]
    for item in journey_ids:
        if item in tracks:
            selected[item] = tracks[item]
    selected.pop(7976, None)
    selected.pop(8471, None)
    return tracks, list(selected.values())


def desired_stage(position: int, total: int) -> int:
    ratio = position / max(1, total - 1)
    if ratio < 0.20:
        return 0
    if ratio < 0.46:
        return 1
    if ratio < 0.73:
        return 2
    return 3


def build_path(candidates: list[Track], start: Track, end: Track, intermediates: int = 26) -> list[Track]:
    pair_cache: dict[tuple[int, int], tuple[float, str, dict[str, float]]] = {}

    def pair(a: Track, b: Track):
        key = (a.id, b.id)
        if key not in pair_cache:
            pair_cache[key] = mix_score(a, b)
        return pair_cache[key]

    beams: list[tuple[float, list[Track]]] = [(0.0, [start])]
    for position in range(intermediates):
        stage = desired_stage(position, intermediates)
        expanded: list[tuple[float, list[Track]]] = []
        for score, path in beams:
            previous = path[-1]
            used_ids = {track.id for track in path}
            used_titles = {norm_text(track.title) for track in path}
            key_run = 1
            for prior in reversed(path[:-1]):
                if prior.key == path[-1].key:
                    key_run += 1
                else:
                    break
            key_counts: dict[str, int] = {}
            for prior in path:
                key_counts[prior.key] = key_counts.get(prior.key, 0) + 1
            artist_counts: dict[str, int] = {}
            for track in path:
                artist_counts[track.artist] = artist_counts.get(track.artist, 0) + 1
            options = []
            for track in candidates:
                if track.id in used_ids or norm_text(track.title) in used_titles:
                    continue
                if abs(track.stage - stage) > 1:
                    continue
                harmonic = key_score(previous.key, track.key)
                if harmonic < 0.70:
                    continue
                if track.key == previous.key and key_run >= 3:
                    continue
                if key_counts.get(track.key, 0) >= 5:
                    continue
                transition, _, _ = pair(previous, track)
                if transition < 0.90:
                    continue
                if position == intermediates - 1:
                    final_harmonic = key_score(track.key, end.key)
                    if final_harmonic < 0.70:
                        continue
                    final_transition, _, _ = pair(track, end)
                    if final_transition < 0.90:
                        continue
                stage_penalty = abs(track.stage - stage) * 0.035
                energy_target = 0.80 if position < intermediates * 0.45 else 0.74 + 0.10 * (position / intermediates)
                energy_penalty = abs(track.energy - energy_target) * 0.04
                artist_penalty = max(0, artist_counts.get(track.artist, 0) - 1) * 0.06
                harmonic_bonus = harmonic * 0.09
                repeated_key_penalty = max(0, key_counts.get(track.key, 0) - 2) * 0.035
                next_score = (
                    score + transition * 1.35 + harmonic_bonus - stage_penalty - energy_penalty
                    - artist_penalty - repeated_key_penalty
                )
                options.append((next_score, path + [track]))
            options.sort(key=lambda item: item[0], reverse=True)
            expanded.extend(options[:28])
        expanded.sort(key=lambda item: item[0], reverse=True)
        # Keep diversity by final track and recent title sequence.
        diverse: dict[tuple[int, ...], tuple[float, list[Track]]] = {}
        for item in expanded:
            signature = tuple(track.id for track in item[1][-3:])
            if signature not in diverse:
                diverse[signature] = item
            if len(diverse) >= 600:
                break
        beams = list(diverse.values())
        if not beams:
            raise RuntimeError(f"No path candidates at position {position}")

    finals = []
    for score, path in beams:
        harmonic = key_score(path[-1].key, end.key)
        if harmonic < 0.70:
            continue
        transition, _, _ = pair(path[-1], end)
        if transition < 0.90:
            continue
        finals.append((score + transition * 2.0 + harmonic * 0.09, path + [end]))
    finals.sort(key=lambda item: item[0], reverse=True)
    return finals[0][1]


def main() -> None:
    all_tracks, candidates = load_tracks()
    print(f"Analyzing {len(candidates)} audio candidates...", flush=True)
    usable: list[Track] = []
    for index, track in enumerate(candidates, 1):
        try:
            analyze_track(track)
            usable.append(track)
        except Exception as exc:
            print(f"SKIP {track.id} {track.artist} - {track.title}: {exc}")
        if index % 20 == 0:
            print(f"  {index}/{len(candidates)}", flush=True)
    start = all_tracks[7565]
    end = all_tracks[8471]
    september = all_tracks[7976]
    pre_closer = all_tracks[7425]
    bridge_two = all_tracks[10100]
    bridge_end = all_tracks[3896]
    first_bridge = all_tracks[13081]
    for fixed in (start, end, september, pre_closer, bridge_two, bridge_end, first_bridge):
        if fixed.id not in {track.id for track in usable}:
            analyze_track(fixed)
            usable.append(fixed)
    # Ensure endpoint objects are the analyzed instances.
    by_id = {track.id: track for track in usable}
    start = by_id[start.id]
    end = by_id[end.id]
    path_candidates = [
        track for track in usable
        if track.id not in (
            start.id, end.id, september.id, bridge_end.id, bridge_two.id, pre_closer.id
            , first_bridge.id
        )
    ]
    path = build_path(path_candidates, first_bridge, bridge_end, intermediates=22)
    path.insert(0, start)
    path.append(bridge_two)
    path.append(pre_closer)
    path.append(end)
    print("\nPATH")
    for index, track in enumerate(path, 1):
        if index == 1:
            print(f"{index:02d}|{track.id}|rb={track.rekordbox_id}|{track.artist}|{track.title}|{track.bpm:.2f}|{track.key}|{track.subgenre}|START")
            continue
        source = path[index - 2]
        score, zones, details = mix_score(source, track)
        print(
            f"{index:02d}|{track.id}|rb={track.rekordbox_id}|{track.artist}|{track.title}|{track.bpm:.2f}|{track.key}|{track.subgenre}|"
            f"{score:.4f}|{zones}|kick={details['kick']:.3f}|perc={details['percussion']:.3f}|band={details['band']:.3f}"
        )
    if september.id in by_id:
        score, zones, details = mix_score(end, by_id[september.id])
        print(
            f"CLOSER|{score:.4f}|{zones}|kick={details['kick']:.3f}|"
            f"perc={details['percussion']:.3f}|band={details['band']:.3f}"
        )


if __name__ == "__main__":
    main()
