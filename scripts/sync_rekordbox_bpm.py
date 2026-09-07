#!/usr/bin/env python3
"""Synchronize Djaly BPM values from the local Rekordbox collection."""

from __future__ import annotations

import argparse
import csv
import io
import json
import re
import unicodedata
import urllib.request
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

from rekordbox_mcp.db.repository import RekordboxRepository


def normalize_path(value: str) -> str:
    return unicodedata.normalize("NFC", (value or "").strip()).casefold()


def normalize_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value or "").casefold()
    return re.sub(r"[^a-z0-9]+", "", normalized)


def get_json(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=120) as response:
        return json.load(response)


def post_json(url: str, payload: dict) -> dict:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=120) as response:
        return json.load(response)


def load_djaly_tracks(base_url: str) -> list[dict]:
    with urllib.request.urlopen(f"{base_url}/api/settings/export/csv", timeout=300) as response:
        content = response.read().decode("utf-8-sig")
    return list(csv.DictReader(io.StringIO(content)))


def load_rekordbox_indexes():
    repository = RekordboxRepository(mode="readonly")
    repository.connect()
    try:
        raw_rows = repository._connection.get_content_table().get_all()
        tracks = repository.get_tracks()
    finally:
        repository.close()

    path_index = defaultdict(list)
    for row in raw_rows:
        bpm = float(row.get("AverageBpm") or 0) / 100.0
        if bpm <= 0:
            continue
        item = {"rekordbox_id": str(row.get("ID")), "bpm": bpm}
        for path in {row.get("FolderPath"), row.get("OrgFolderPath")}:
            if path:
                path_index[normalize_path(path)].append(item)

    metadata_index = defaultdict(list)
    for track in tracks:
        if track.bpm and track.bpm > 0:
            metadata_index[(normalize_text(track.artist), normalize_text(track.title))].append(
                {"rekordbox_id": str(track.id), "bpm": float(track.bpm)}
            )
    return path_index, metadata_index, len(raw_rows)


def unique_candidate(candidates: list[dict]) -> tuple[dict | None, bool]:
    distinct = {(item["rekordbox_id"], item["bpm"]): item for item in candidates}
    values = list(distinct.values())
    if len(values) == 1:
        return values[0], False
    bpms = {item["bpm"] for item in values}
    if values and len(bpms) == 1:
        return values[0], False
    return None, bool(values)


def build_plan(djaly_tracks: list[dict], path_index, metadata_index):
    updates = []
    rollback = []
    counts = defaultdict(int)
    djaly_metadata_counts = Counter(
        (normalize_text(track.get("artist", "")), normalize_text(track.get("title", "")))
        for track in djaly_tracks
    )
    for track in djaly_tracks:
        candidate, ambiguous = unique_candidate(path_index.get(normalize_path(track["filepath"]), []))
        method = "path"
        if candidate is None and not ambiguous:
            key = (normalize_text(track.get("artist", "")), normalize_text(track.get("title", "")))
            if djaly_metadata_counts[key] == 1:
                metadata_candidates = list(
                    {
                        (item["rekordbox_id"], item["bpm"]): item
                        for item in metadata_index.get(key, [])
                    }.values()
                )
                if len(metadata_candidates) == 1:
                    candidate = metadata_candidates[0]
                elif metadata_candidates:
                    ambiguous = True
            method = "metadata"
        if ambiguous:
            counts[f"{method}_ambiguous"] += 1
            continue
        if candidate is None:
            counts["unmatched"] += 1
            continue
        counts[f"{method}_matched"] += 1
        old_bpm = float(track.get("bpm") or 0)
        new_bpm = candidate["bpm"]
        if abs(old_bpm - new_bpm) < 0.005:
            counts["already_equal"] += 1
            continue
        updates.append(
            {
                "filepath": track["filepath"],
                "old_bpm": old_bpm,
                "new_bpm": new_bpm,
                "rekordbox_id": candidate["rekordbox_id"],
                "match_method": method,
            }
        )
        rollback.append({"data": {"filepath": track["filepath"], "bpm": old_bpm}})
    counts["updates"] = len(updates)
    return updates, rollback, dict(counts)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:48123")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--prepare", action="store_true")
    parser.add_argument("--batch-size", type=int, default=500)
    parser.add_argument(
        "--audit-dir",
        default=str(Path.home() / "Library/Application Support/Djaly/backups"),
    )
    args = parser.parse_args()

    djaly_tracks = load_djaly_tracks(args.base_url)
    path_index, metadata_index, rekordbox_count = load_rekordbox_indexes()
    updates, rollback, counts = build_plan(djaly_tracks, path_index, metadata_index)
    summary = {
        "djaly_tracks": len(djaly_tracks),
        "rekordbox_tracks": rekordbox_count,
        **counts,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if not args.apply and not args.prepare:
        return

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    audit_dir = Path(args.audit_dir) / f"{timestamp}-before-rekordbox-bpm-sync"
    audit_dir.mkdir(parents=True, exist_ok=False)
    (audit_dir / "rollback.json").write_text(
        json.dumps({"updates": rollback}, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (audit_dir / "changes.json").write_text(
        json.dumps({"summary": summary, "changes": updates}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    if not args.apply:
        print(json.dumps({"audit_dir": str(audit_dir)}, ensure_ascii=False))
        return

    applied = 0
    for start in range(0, len(updates), args.batch_size):
        batch = updates[start : start + args.batch_size]
        payload = {
            "updates": [
                {"data": {"filepath": item["filepath"], "bpm": item["new_bpm"]}}
                for item in batch
            ]
        }
        result = post_json(f"{args.base_url}/api/settings/metadata/import/execute", payload)
        applied += int(result.get("updated", 0))
        print(f"applied {applied}/{len(updates)}")
    if applied != len(updates):
        raise RuntimeError(f"Expected {len(updates)} updates, API reported {applied}")
    print(json.dumps({"applied": applied, "audit_dir": str(audit_dir)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
