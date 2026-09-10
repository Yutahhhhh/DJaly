#!/usr/bin/env python3
"""Create/update Rekordbox GENRES playlists from plumdeck's verified library."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from uuid import uuid4

import os
import platformdirs

import duckdb

from rekordbox_mcp.config import Settings
from rekordbox_mcp.db.connection import db6_tables
from rekordbox_mcp.db.repository import RekordboxRepository
from rekordbox_mcp.domain.models import OperationMode, Playlist

PLUMDECK_DB = Path(os.environ.get("DB_PATH") or str(Path(platformdirs.user_data_dir("plumdeck", "plumdeck")) / "plumdeck.duckdb")).expanduser()
ROOT_NAME = "GENRES"
SPLIT_AT = 900
MIN_SUBGENRE_TRACKS = 20


def next_seq(records: list[dict[str, str]], parent_id: str) -> int:
    return max((int(row["seq"] or 0) for row in records if row["parent_id"] == parent_id), default=-1) + 1


def main() -> None:
    # plumdeck is authoritative for classification; Rekordbox is authoritative for IDs.
    with duckdb.connect(str(PLUMDECK_DB), read_only=True) as db:
        rows = db.execute(
            """
            SELECT filepath, trim(genre) AS genre, trim(subgenre) AS subgenre
            FROM tracks
            WHERE trim(coalesce(genre, '')) NOT IN ('', 'Unknown')
            """
        ).fetchall()

    by_genre: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for filepath, genre, subgenre in rows:
        by_genre[genre].append((filepath, subgenre or ""))

    target_paths: dict[tuple[str, str], set[str]] = defaultdict(set)
    for genre, tracks in by_genre.items():
        subgenre_counts: dict[str, int] = defaultdict(int)
        for _, subgenre in tracks:
            subgenre_counts[subgenre] += 1
        split = len(tracks) >= SPLIT_AT
        for filepath, subgenre in tracks:
            if split and subgenre_counts[subgenre] >= MIN_SUBGENRE_TRACKS:
                leaf = subgenre or "Other"
            elif split:
                leaf = "Other"
            else:
                leaf = genre
            target_paths[(genre, leaf)].add(filepath)

    settings = Settings(mode="masterdb")
    repo = RekordboxRepository(settings, OperationMode.MASTERDB)
    repo.connect()
    try:
        if repo._connection.is_rekordbox_running():
            raise RuntimeError("Rekordbox is running; close it before writing playlists.")

        session = repo._connection.db.session
        track_rows = session.query(
            db6_tables.DjmdContent.ID, db6_tables.DjmdContent.FolderPath
        ).all()
        rekordbox_ids = {str(path): int(track_id) for track_id, path in track_rows if path}

        playlist_rows = session.query(
            db6_tables.DjmdPlaylist.ID,
            db6_tables.DjmdPlaylist.Name,
            db6_tables.DjmdPlaylist.ParentID,
            db6_tables.DjmdPlaylist.Seq,
            db6_tables.DjmdPlaylist.Attribute,
        ).all()
        records = [
            {"id": str(row[0]), "name": row[1], "parent_id": str(row[2] or "root"), "seq": row[3], "attribute": row[4]}
            for row in playlist_rows
        ]

        def ensure(name: str, parent_id: str, attribute: int) -> str:
            for row in records:
                if row["name"] == name and row["parent_id"] == parent_id and row["attribute"] == attribute:
                    return row["id"]
            playlist = Playlist(
                id=str(uuid4()), name=name, parent_id=parent_id,
                seq=next_seq(records, parent_id), attribute=attribute,
            )
            saved = repo.save_playlist(playlist)
            record = {"id": saved.id, "name": name, "parent_id": parent_id, "seq": saved.seq, "attribute": attribute}
            records.append(record)
            return saved.id

        root_id = ensure(ROOT_NAME, "root", 1)
        result: list[tuple[str, str, int, int]] = []
        missing = 0
        for genre in sorted(by_genre, key=str.casefold):
            genre_folder_id = ensure(genre, root_id, 1)
            for (target_genre, leaf), filepaths in sorted(target_paths.items(), key=lambda x: (x[0][0].casefold(), x[0][1].casefold())):
                if target_genre != genre:
                    continue
                playlist_id = ensure(leaf, genre_folder_id, 0)
                ids = [rekordbox_ids[path] for path in sorted(filepaths) if path in rekordbox_ids]
                missing += len(filepaths) - len(ids)
                repo.set_playlist_tracks(playlist_id, ids)
                result.append((genre, leaf, len(ids), len(filepaths) - len(ids)))

        print(f"Created/updated {len(result)} playlists in {ROOT_NAME}.")
        print(f"Matched {sum(item[2] for item in result)} tracks; {missing} plumdeck tracks were not in Rekordbox.")
        for genre, leaf, matched, unmatched in result:
            print(f"{genre} / {leaf}: {matched}" + (f" (unmatched: {unmatched})" if unmatched else ""))
    finally:
        repo.close()


if __name__ == "__main__":
    main()
