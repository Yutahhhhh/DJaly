"""
infra/database/compaction.ensure_healthy_db のテスト。

- 旧スキーマ (v3, JSON カラム) の DB を v4 (BLOB カラム) へファイル再構築で移行できる
- データ / シーケンス現在値 / 波形のダウンサンプルが保たれる
- 既に v4 のファイルは肥大していなければ何もしない
- 肥大した v4 ファイルは変換なしで再構築 (コンパクション) される
"""
import glob
import json
import os

import duckdb
import pytest

import infra.database.compaction as compaction
from domain.models.track import TrackAnalysis
from infra.database.compaction import ensure_healthy_db
from infra.database.schema import get_schema_statements


def _make_legacy_v3_db(path: str, n_tracks: int = 5) -> None:
    con = duckdb.connect(path)
    for seq in ("seq_tracks_id", "seq_setlists_id", "seq_setlist_tracks_id"):
        con.execute(f"CREATE SEQUENCE {seq} START 1")
    con.execute(
        "CREATE TABLE tracks (id INTEGER PRIMARY KEY DEFAULT nextval('seq_tracks_id'), "
        "filepath VARCHAR UNIQUE NOT NULL, title VARCHAR, artist VARCHAR, genre VARCHAR, bpm FLOAT)"
    )
    con.execute(
        "CREATE TABLE track_analyses (track_id INTEGER PRIMARY KEY, beat_positions JSON, "
        "waveform_peaks JSON, features_extra_json VARCHAR DEFAULT '{}')"
    )
    con.execute(
        "CREATE TABLE track_embeddings (track_id INTEGER PRIMARY KEY, model_name VARCHAR DEFAULT "
        "'musicnn', embedding_json VARCHAR DEFAULT '[]', updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
    )
    con.execute("CREATE TABLE lyrics (track_id INTEGER PRIMARY KEY, content VARCHAR DEFAULT '')")
    con.execute(
        "CREATE TABLE setlists (id INTEGER PRIMARY KEY DEFAULT nextval('seq_setlists_id'), name VARCHAR NOT NULL)"
    )
    con.execute(
        "CREATE TABLE setlist_tracks (id INTEGER PRIMARY KEY DEFAULT nextval('seq_setlist_tracks_id'), "
        "setlist_id INTEGER, track_id INTEGER, position INTEGER)"
    )
    con.execute("CREATE TABLE settings (key VARCHAR PRIMARY KEY, value VARCHAR NOT NULL)")
    con.execute("CREATE TABLE schema_info (key VARCHAR PRIMARY KEY, value VARCHAR NOT NULL)")
    con.execute("INSERT INTO schema_info VALUES ('version', '3')")

    waveform = [(j % 100) / 100.0 for j in range(2000)]
    beats = [round(x * 0.5, 3) for x in range(300)]
    for i in range(1, n_tracks + 1):
        con.execute(
            "INSERT INTO tracks (filepath, title, artist, genre, bpm) VALUES (?, ?, ?, ?, ?)",
            [f"/m/{i}.mp3", f"T{i}", "A", "House", 120.0 + i],
        )
        con.execute(
            "INSERT INTO track_analyses VALUES (?, ?, ?, ?)",
            [i, json.dumps(beats), json.dumps(waveform), json.dumps({"bpm_confidence": 0.9})],
        )
        con.execute(
            "INSERT INTO track_embeddings (track_id, embedding_json) VALUES (?, ?)",
            [i, json.dumps([0.1] * 200)],
        )
    con.execute("INSERT INTO setlists (name) VALUES ('S1')")
    con.execute("INSERT INTO setlist_tracks (setlist_id, track_id, position) VALUES (1, 2, 0)")
    con.close()


def test_migrates_v3_to_v4_and_preserves_data(tmp_path):
    db = str(tmp_path / "legacy.duckdb")
    _make_legacy_v3_db(db, n_tracks=5)

    ensure_healthy_db(db)

    con = duckdb.connect(db)
    try:
        assert con.execute("SELECT value FROM schema_info WHERE key='version'").fetchone()[0] == "5"
        cols = {
            r[0]
            for r in con.execute(
                "SELECT column_name FROM information_schema.columns WHERE table_name='track_analyses'"
            ).fetchall()
        }
        assert cols == {"track_id", "beats_f32", "waveform_u8", "features_extra_json"}
        assert con.execute("SELECT count(*) FROM tracks").fetchone()[0] == 5
        assert con.execute("SELECT count(*) FROM track_embeddings").fetchone()[0] == 5
        assert con.execute("SELECT setlist_id, track_id, position FROM setlist_tracks").fetchone() == (1, 2, 0)

        wu8, bf32, fx = con.execute(
            "SELECT waveform_u8, beats_f32, features_extra_json FROM track_analyses WHERE track_id=1"
        ).fetchone()
        ta = TrackAnalysis(track_id=1)
        ta.waveform_u8, ta.beats_f32 = wu8, bf32
        assert len(ta.waveform_peaks) == 500          # 2000 点 -> 500 点にダウンサンプル
        assert len(ta.beat_positions) == 300
        assert ta.beat_positions[-1] == pytest.approx(149.5)
        assert json.loads(fx)["bpm_confidence"] == 0.9

        # シーケンスは既存 id の続きから採番される
        con.execute("INSERT INTO tracks (filepath, title, artist, genre, bpm) VALUES ('/m/new.mp3','N','A','House',130)")
        assert con.execute("SELECT id FROM tracks WHERE filepath='/m/new.mp3'").fetchone()[0] == 6
    finally:
        con.close()

    # 旧ファイルは .bak として残る
    assert len(glob.glob(db + ".bak-v5-*")) == 1


def test_second_run_is_noop(tmp_path):
    db = str(tmp_path / "legacy.duckdb")
    _make_legacy_v3_db(db, n_tracks=3)

    ensure_healthy_db(db)
    size_after_migrate = os.path.getsize(db)
    bak_count = len(glob.glob(db + ".bak-v5-*"))

    ensure_healthy_db(db)  # 2 回目

    assert os.path.getsize(db) == size_after_migrate
    assert not os.path.exists(db + ".rebuild")
    assert len(glob.glob(db + ".bak-v5-*")) == bak_count


def test_missing_file_is_noop(tmp_path):
    ensure_healthy_db(str(tmp_path / "does_not_exist.duckdb"))  # 例外を投げない


def test_compacts_bloated_v4_file(tmp_path, monkeypatch):
    db = str(tmp_path / "v4.duckdb")
    con = duckdb.connect(db)
    for stmt in get_schema_statements():
        con.execute(stmt)
    con.execute(
        "INSERT INTO schema_info VALUES ('version','4') ON CONFLICT (key) DO UPDATE SET value=excluded.value"
    )
    for i in range(1, 4):
        con.execute(
            "INSERT INTO tracks (filepath, title, artist, genre, bpm) VALUES (?, ?, ?, ?, ?)",
            [f"/m/{i}.mp3", f"T{i}", "A", "House", 120.0],
        )
        con.execute(
            "INSERT INTO track_analyses (track_id, beats_f32, waveform_u8, features_extra_json) VALUES (?, ?, ?, ?)",
            [i, b"\x00" * 40, bytes(range(256)), "{}"],
        )
    con.close()

    # しきい値を下げて肥大とみなさせる
    monkeypatch.setattr(compaction, "COMPACT_MIN_BYTES", 1)
    monkeypatch.setattr(compaction, "COMPACT_BYTES_PER_TRACK", 1)
    monkeypatch.setattr(compaction, "COMPACT_RATIO_LIMIT", 1)

    ensure_healthy_db(db)

    con = duckdb.connect(db)
    try:
        assert con.execute("SELECT value FROM schema_info WHERE key='version'").fetchone()[0] == "5"
        assert con.execute("SELECT count(*) FROM tracks").fetchone()[0] == 3
        assert con.execute(
            "SELECT octet_length(waveform_u8) FROM track_analyses WHERE track_id=1"
        ).fetchone()[0] == 256
    finally:
        con.close()
    assert len(glob.glob(db + ".bak-v5-*")) == 1
