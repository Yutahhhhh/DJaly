from typing import Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.engine import Engine
from utils.logger import get_logger

logger = get_logger(__name__)

# 現在のスキーマバージョン
# v4: track_analyses の波形/ビートを JSON テキスト -> BLOB 化 (DuckDB ファイル肥大化対策)。
#     v4 への移行は infra/database/compaction.py がファイル再構築で行う。
CURRENT_SCHEMA_VERSION = 4

# id を採番するシーケンス (テーブルより先に作成する必要がある)
SEQUENCES = {
    "seq_tracks_id": "tracks",
    "seq_setlists_id": "setlists",
    "seq_setlist_tracks_id": "setlist_tracks",
    "seq_wordplay_pairs_id": "wordplay_pairs",
    "seq_play_history_id": "play_history",
    "seq_recordings_id": "recordings",
}

# 再構築時にそのままコピーできる (変換不要の) テーブル
PLAIN_TABLES = [
    "tracks", "lyrics", "setlists", "setlist_tracks", "wordplay_pairs",
    "track_performance_metadata", "track_grid_candidates", "rekordbox_sources", "rekordbox_playlists",
    "rekordbox_playlist_tracks", "play_sessions", "play_history", "recordings",
    "settings", "schema_info"
]
# 再構築時に行単位の変換が必要なテーブル
CONVERTED_TABLES = ["track_analyses", "track_embeddings"]
ALL_TABLES = PLAIN_TABLES + CONVERTED_TABLES

# バージョンごとのマイグレーション SQL (version: [statements])
# NOTE: v4 は ALTER では表現できない (JSON->BLOB 変換) ため compaction.py で処理する。
MIGRATIONS = {
    2: [
        # ワードプレイ用キーワード抽出結果の永続キャッシュ
        "ALTER TABLE lyrics ADD COLUMN IF NOT EXISTS keywords_json VARCHAR",
        "ALTER TABLE lyrics ADD COLUMN IF NOT EXISTS keywords_content_hash VARCHAR",
    ],
    3: [
        # Prompt/Preset 機能の廃止に伴うテーブル削除
        "DROP TABLE IF EXISTS presets",
        "DROP TABLE IF EXISTS prompts",
    ],
}

# Additive fields that must also reach databases already marked schema v4. These
# do not require the file rebuild associated with a schema-version migration.
COMPATIBILITY_STATEMENTS = [
    "ALTER TABLE wordplay_pairs ADD COLUMN IF NOT EXISTS "
    "source_section_position VARCHAR DEFAULT 'unknown'",
    "ALTER TABLE wordplay_pairs ADD COLUMN IF NOT EXISTS "
    "target_section_position VARCHAR DEFAULT 'unknown'",
    "ALTER TABLE wordplay_pairs ADD COLUMN IF NOT EXISTS "
    "source_cue_mode VARCHAR DEFAULT 'section_end'",
    "ALTER TABLE wordplay_pairs ADD COLUMN IF NOT EXISTS source_cue_end_timestamp DOUBLE",
    "ALTER TABLE wordplay_pairs ADD COLUMN IF NOT EXISTS target_intro_timestamp DOUBLE",
    "ALTER TABLE wordplay_pairs ADD COLUMN IF NOT EXISTS target_landing_timestamp DOUBLE",
    # 録音に名前を付けて保存できるようにする。既存の録音は名前なしのまま残る。
    "ALTER TABLE recordings ADD COLUMN IF NOT EXISTS artist VARCHAR",
    "ALTER TABLE recordings ADD COLUMN IF NOT EXISTS title VARCHAR",
]


def get_table_ddl() -> Dict[str, str]:
    """
    テーブル名 -> CREATE TABLE 文。

    DuckDBの制約回避：
    DuckDBでは外部キー(FK)が設定されているテーブルの更新(UPDATE)が失敗しやすいため、
    物理的な FOREIGN KEY 句を削除し、インデックスと主キーのみで構成します。
    """
    return {
        "track_grid_candidates": """
            CREATE TABLE IF NOT EXISTS track_grid_candidates (
                track_id INTEGER NOT NULL,
                source VARCHAR NOT NULL,
                grid_json VARCHAR NOT NULL,
                fingerprint VARCHAR NOT NULL,
                provenance_json VARCHAR NOT NULL,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (track_id, source)
            )
        """,
        "tracks": """
            CREATE TABLE IF NOT EXISTS tracks (
                id INTEGER PRIMARY KEY DEFAULT nextval('seq_tracks_id'),
                filepath VARCHAR UNIQUE NOT NULL,
                title VARCHAR,
                artist VARCHAR,
                album VARCHAR,
                genre VARCHAR,
                subgenre VARCHAR DEFAULT '',
                year INTEGER,
                bpm FLOAT,
                key VARCHAR,
                scale VARCHAR,
                duration FLOAT,
                energy FLOAT DEFAULT 0.0,
                danceability FLOAT DEFAULT 0.0,
                loudness FLOAT DEFAULT -60.0,
                brightness FLOAT DEFAULT 0.0,
                noisiness FLOAT DEFAULT 0.0,
                contrast FLOAT DEFAULT 0.0,
                loudness_range FLOAT DEFAULT 0.0,
                spectral_flux FLOAT DEFAULT 0.0,
                spectral_rolloff FLOAT DEFAULT 0.0,
                is_genre_verified BOOLEAN DEFAULT FALSE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """,
        # v4: beat_positions / waveform_peaks (JSON テキスト) を BLOB 化。
        #   - waveform_u8 : 0..1 振幅を 500 点 uint8 にダウンサンプルした生バイト
        #   - beats_f32   : ビート位置(秒) の float32 生バイト
        "track_analyses": """
            CREATE TABLE IF NOT EXISTS track_analyses (
                track_id INTEGER PRIMARY KEY,
                beats_f32 BLOB,
                waveform_u8 BLOB,
                features_extra_json VARCHAR DEFAULT '{}'
            )
        """,
        "track_embeddings": """
            CREATE TABLE IF NOT EXISTS track_embeddings (
                track_id INTEGER PRIMARY KEY,
                model_name VARCHAR DEFAULT 'musicnn',
                embedding_json VARCHAR DEFAULT '[]',
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """,
        "lyrics": """
            CREATE TABLE IF NOT EXISTS lyrics (
                track_id INTEGER PRIMARY KEY,
                content VARCHAR DEFAULT '',
                source VARCHAR DEFAULT 'user',
                language VARCHAR,
                keywords_json VARCHAR,
                keywords_content_hash VARCHAR,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """,
        "setlists": """
            CREATE TABLE IF NOT EXISTS setlists (
                id INTEGER PRIMARY KEY DEFAULT nextval('seq_setlists_id'),
                name VARCHAR NOT NULL,
                description VARCHAR,
                display_order INTEGER DEFAULT 0,
                genre VARCHAR,
                target_duration FLOAT,
                rating INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """,
        "setlist_tracks": """
            CREATE TABLE IF NOT EXISTS setlist_tracks (
                id INTEGER PRIMARY KEY DEFAULT nextval('seq_setlist_tracks_id'),
                setlist_id INTEGER NOT NULL,
                track_id INTEGER NOT NULL,
                position INTEGER NOT NULL,
                transition_note VARCHAR,
                wordplay_json VARCHAR,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """,
        "wordplay_pairs": """
            CREATE TABLE IF NOT EXISTS wordplay_pairs (
                id INTEGER PRIMARY KEY DEFAULT nextval('seq_wordplay_pairs_id'),
                from_track_id INTEGER NOT NULL,
                to_track_id INTEGER NOT NULL,
                keyword VARCHAR NOT NULL,
                normalized_keyword VARCHAR NOT NULL,
                source_phrase VARCHAR NOT NULL,
                target_phrase VARCHAR NOT NULL,
                source_section_position VARCHAR NOT NULL DEFAULT 'unknown',
                target_section_position VARCHAR NOT NULL DEFAULT 'unknown',
                source_cue_mode VARCHAR NOT NULL DEFAULT 'section_end',
                from_timestamp DOUBLE,
                source_cue_end_timestamp DOUBLE,
                to_timestamp DOUBLE,
                target_intro_timestamp DOUBLE,
                target_landing_timestamp DOUBLE,
                transition_notes VARCHAR NOT NULL DEFAULT '',
                source_url VARCHAR NOT NULL DEFAULT '',
                evidence_type VARCHAR NOT NULL DEFAULT 'hypothesis',
                verification_status VARCHAR NOT NULL DEFAULT 'unverified',
                status VARCHAR NOT NULL DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                CONSTRAINT uq_wordplay_pair_direction_keyword
                    UNIQUE (from_track_id, to_track_id, normalized_keyword)
            )
        """,
        "track_performance_metadata": """
            CREATE TABLE IF NOT EXISTS track_performance_metadata (
                track_id INTEGER PRIMARY KEY,
                cue_points_json VARCHAR NOT NULL DEFAULT '[]',
                loops_json VARCHAR NOT NULL DEFAULT '[]',
                beat_grid_json VARCHAR,
                revision INTEGER NOT NULL DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """,
        "rekordbox_sources": """
            CREATE TABLE IF NOT EXISTS rekordbox_sources (
                id VARCHAR PRIMARY KEY,
                name VARCHAR NOT NULL,
                imported_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """,
        "rekordbox_playlists": """
            CREATE TABLE IF NOT EXISTS rekordbox_playlists (
                source_id VARCHAR NOT NULL,
                external_id VARCHAR NOT NULL,
                parent_external_id VARCHAR,
                name VARCHAR NOT NULL,
                sort_order INTEGER DEFAULT 0,
                kind VARCHAR NOT NULL DEFAULT 'playlist',
                PRIMARY KEY (source_id, external_id)
            )
        """,
        "rekordbox_playlist_tracks": """
            CREATE TABLE IF NOT EXISTS rekordbox_playlist_tracks (
                source_id VARCHAR NOT NULL,
                playlist_external_id VARCHAR NOT NULL,
                position INTEGER NOT NULL,
                external_track_id VARCHAR,
                local_track_id INTEGER,
                filepath VARCHAR,
                title VARCHAR,
                artist VARCHAR,
                bpm FLOAT,
                musical_key VARCHAR,
                duration FLOAT,
                PRIMARY KEY (source_id, playlist_external_id, position)
            )
        """,
        "play_sessions": """
            CREATE TABLE IF NOT EXISTS play_sessions (
                id VARCHAR PRIMARY KEY,
                started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                ended_at TIMESTAMP,
                deck_count INTEGER NOT NULL DEFAULT 2
            )
        """,
        "play_history": """
            CREATE TABLE IF NOT EXISTS play_history (
                id INTEGER PRIMARY KEY DEFAULT nextval('seq_play_history_id'),
                event_key VARCHAR UNIQUE NOT NULL,
                session_id VARCHAR NOT NULL,
                deck VARCHAR NOT NULL,
                track_id INTEGER NOT NULL,
                loaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                first_played_at TIMESTAMP,
                ended_at TIMESTAMP,
                played_ms BIGINT NOT NULL DEFAULT 0,
                completed BOOLEAN NOT NULL DEFAULT FALSE,
                reason VARCHAR
            )
        """,
        "recordings": """
            CREATE TABLE IF NOT EXISTS recordings (
                id INTEGER PRIMARY KEY DEFAULT nextval('seq_recordings_id'),
                recording_key VARCHAR UNIQUE NOT NULL,
                session_id VARCHAR,
                filepath VARCHAR NOT NULL,
                started_at TIMESTAMP NOT NULL,
                ended_at TIMESTAMP,
                duration_ms BIGINT NOT NULL DEFAULT 0,
                status VARCHAR NOT NULL DEFAULT 'recording',
                error VARCHAR,
                artist VARCHAR,
                title VARCHAR
            )
        """,
        "settings": """
            CREATE TABLE IF NOT EXISTS settings (
                key VARCHAR PRIMARY KEY,
                value VARCHAR NOT NULL
            )
        """,
        "schema_info": """
            CREATE TABLE IF NOT EXISTS schema_info (
                key VARCHAR PRIMARY KEY,
                value VARCHAR NOT NULL
            )
        """,
    }


def get_schema_statements(seq_starts: Optional[Dict[str, int]] = None) -> List[str]:
    """
    スキーマ構築用の DDL 文を「実行すべき順」で返す。
    シーケンスをテーブルより先に作る。`seq_starts` で各シーケンスの開始値を指定できる
    (ファイル再構築時に既存の MAX(id)+1 から再開させるため)。
    """
    seq_starts = seq_starts or {}
    stmts: List[str] = []
    for seq_name in SEQUENCES:
        start = int(seq_starts.get(seq_name, 1) or 1)
        stmts.append(f"CREATE SEQUENCE IF NOT EXISTS {seq_name} START {start}")
    for ddl in get_table_ddl().values():
        stmts.append(" ".join(ddl.split()))
    return stmts


def get_current_schema_version(conn) -> int:
    try:
        result = conn.execute(text("SELECT value FROM schema_info WHERE key = 'version'"))
        row = result.fetchone()
        return int(row[0]) if row else 0
    except Exception:
        return 0


def set_schema_version(conn, version: int):
    conn.execute(text("""
        INSERT INTO schema_info (key, value) VALUES ('version', :version)
        ON CONFLICT (key) DO UPDATE SET value = :version
    """), {"version": str(version)})


def init_raw_db(conn_engine: Engine):
    logger.info("Initializing DuckDB schema...")
    try:
        with conn_engine.begin() as conn:
            for stmt in get_schema_statements():
                conn.execute(text(stmt))
            for stmt in COMPATIBILITY_STATEMENTS:
                conn.execute(text(stmt))

            current_version = get_current_schema_version(conn)
            if current_version < CURRENT_SCHEMA_VERSION:
                for version in range(current_version + 1, CURRENT_SCHEMA_VERSION + 1):
                    for stmt in MIGRATIONS.get(version, []):
                        logger.info(f"Applying migration v{version}: {stmt}")
                        conn.execute(text(stmt))
                set_schema_version(conn, CURRENT_SCHEMA_VERSION)
    except Exception as e:
        logger.error(f"Failed to initialize database schema: {e}")
        raise e
