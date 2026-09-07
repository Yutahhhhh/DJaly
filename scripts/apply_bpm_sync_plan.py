#!/usr/bin/env python3
"""Apply a prepared Rekordbox BPM sync plan to a stopped Djaly database."""

from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

import duckdb


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("database")
    parser.add_argument("plan")
    args = parser.parse_args()

    database = Path(args.database).resolve()
    plan_path = Path(args.plan).resolve()
    payload = json.loads(plan_path.read_text(encoding="utf-8"))
    changes = payload["changes"]
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = database.with_name(f"{database.name}.before-rekordbox-bpm-sync-{timestamp}")

    connection = duckdb.connect(str(database))
    try:
        connection.execute("CHECKPOINT")
    finally:
        connection.close()
    shutil.copy2(database, backup)

    synced_at = datetime.now(timezone.utc).isoformat()
    connection = duckdb.connect(str(database))
    applied = 0
    try:
        connection.execute("BEGIN TRANSACTION")
        for change in changes:
            row = connection.execute(
                "SELECT id, bpm FROM tracks WHERE filepath = ?",
                [change["filepath"]],
            ).fetchone()
            if row is None:
                raise RuntimeError(f"Track disappeared: {change['filepath']}")
            track_id, current_bpm = row
            if abs(float(current_bpm) - float(change["old_bpm"])) >= 0.005:
                raise RuntimeError(f"BPM changed after planning for track {track_id}")
            connection.execute(
                "UPDATE tracks SET bpm = ? WHERE id = ? AND filepath = ?",
                [change["new_bpm"], track_id, change["filepath"]],
            )

            analysis_row = connection.execute(
                "SELECT features_extra_json FROM track_analyses WHERE track_id = ?",
                [track_id],
            ).fetchone()
            if analysis_row is not None:
                try:
                    extras = json.loads(analysis_row[0] or "{}")
                except (TypeError, json.JSONDecodeError):
                    extras = {}
                extras["bpm_authority"] = {
                    "source": "rekordbox",
                    "rekordbox_id": change["rekordbox_id"],
                    "synced_at": synced_at,
                    "match_method": change["match_method"],
                }
                connection.execute(
                    "UPDATE track_analyses SET features_extra_json = ? WHERE track_id = ?",
                    [json.dumps(extras, ensure_ascii=False), track_id],
                )
            applied += 1

        mismatches = 0
        for change in changes:
            bpm = connection.execute(
                "SELECT bpm FROM tracks WHERE filepath = ?", [change["filepath"]]
            ).fetchone()[0]
            if abs(float(bpm) - float(change["new_bpm"])) >= 0.005:
                mismatches += 1
        if mismatches:
            raise RuntimeError(f"Verification found {mismatches} BPM mismatches")
        connection.execute("COMMIT")
        connection.execute("CHECKPOINT")
    except Exception:
        connection.execute("ROLLBACK")
        raise
    finally:
        connection.close()

    print(
        json.dumps(
            {"applied": applied, "backup": str(backup), "synced_at": synced_at},
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
