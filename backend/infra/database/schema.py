from typing import Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.engine import Engine
from utils.logger import get_logger

logger = get_logger(__name__)

# 現在のスキーマバージョン
# v4: track_analyses の波形/ビートを JSON テキスト -> BLOB 化 (DuckDB ファイル肥大化対策)。
#     v4 への移行は infra/database/compaction.py がファイル再構築で行う。
# v5: library workflow tools (media repair, backup, versions, planned set timing,
#     audio/controller presets, USB handoff, recording timeline and Play imports).
CURRENT_SCHEMA_VERSION = 5

# id を採番するシーケンス (テーブルより先に作成する必要がある)
SEQUENCES = {
    "seq_tracks_id": "tracks",
    "seq_setlists_id": "setlists",
    "seq_setlist_tracks_id": "setlist_tracks",
    "seq_wordplay_pairs_id": "wordplay_pairs",
    "seq_play_history_id": "play_history",
    "seq_recordings_id": "recordings",
    "seq_track_version_groups_id": "track_version_groups",
    "seq_recording_segments_id": "recording_segments",
}

# 再構築時にそのままコピーできる (変換不要の) テーブル
PLAIN_TABLES = [
    "tracks", "lyrics", "setlists", "setlist_tracks", "wordplay_pairs",
    "track_performance_metadata", "track_grid_candidates", "rekordbox_sources", "rekordbox_playlists",
    "rekordbox_playlist_tracks", "play_sessions", "play_history", "recordings",
    "settings", "schema_info", "track_media", "media_repair_operations",
    "operation_journal", "track_version_groups", "track_version_members",
    "audio_presets", "controller_profiles", "controller_device_bindings",
    "usb_devices", "usb_exports", "recording_segments", "import_batches",
    "import_items", "import_target_intents"
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
    5: [],
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
    "ALTER TABLE recordings ADD COLUMN IF NOT EXISTS source VARCHAR DEFAULT 'internal'",
    "ALTER TABLE recordings ADD COLUMN IF NOT EXISTS sample_rate_hz INTEGER",
    "ALTER TABLE recordings ADD COLUMN IF NOT EXISTS frame_count BIGINT",
    "ALTER TABLE recordings ADD COLUMN IF NOT EXISTS timeline_quality VARCHAR DEFAULT 'unavailable'",
    "ALTER TABLE recordings ADD COLUMN IF NOT EXISTS timeline_dropped_events BIGINT DEFAULT 0",
    "ALTER TABLE recordings ADD COLUMN IF NOT EXISTS revision INTEGER DEFAULT 1",
    "ALTER TABLE setlist_tracks ADD COLUMN IF NOT EXISTS in_ms DOUBLE DEFAULT 0",
    "ALTER TABLE setlist_tracks ADD COLUMN IF NOT EXISTS out_ms DOUBLE",
    "ALTER TABLE setlist_tracks ADD COLUMN IF NOT EXISTS playback_rate DOUBLE DEFAULT 1",
    "ALTER TABLE setlist_tracks ADD COLUMN IF NOT EXISTS extra_duration_ms DOUBLE DEFAULT 0",
    "ALTER TABLE setlist_tracks ADD COLUMN IF NOT EXISTS overlap_next_ms DOUBLE DEFAULT 0",
    "ALTER TABLE setlist_tracks ADD COLUMN IF NOT EXISTS revision INTEGER DEFAULT 1",
    "ALTER TABLE import_batches ADD COLUMN IF NOT EXISTS origin VARCHAR DEFAULT 'native_file_drop'",
    "ALTER TABLE import_batches ADD COLUMN IF NOT EXISTS analysis_profile VARCHAR DEFAULT 'auto'",
    "ALTER TABLE import_batches ADD COLUMN IF NOT EXISTS effective_analysis_profile VARCHAR",
    "ALTER TABLE import_items ADD COLUMN IF NOT EXISTS analysis_level VARCHAR",
    "ALTER TABLE tracks ADD COLUMN IF NOT EXISTS analysis_level VARCHAR",
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
                analysis_level VARCHAR,
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
                in_ms DOUBLE NOT NULL DEFAULT 0,
                out_ms DOUBLE,
                playback_rate DOUBLE NOT NULL DEFAULT 1,
                extra_duration_ms DOUBLE NOT NULL DEFAULT 0,
                overlap_next_ms DOUBLE NOT NULL DEFAULT 0,
                revision INTEGER NOT NULL DEFAULT 1,
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
                title VARCHAR,
                source VARCHAR NOT NULL DEFAULT 'internal',
                sample_rate_hz INTEGER,
                frame_count BIGINT,
                timeline_quality VARCHAR NOT NULL DEFAULT 'unavailable',
                timeline_dropped_events BIGINT NOT NULL DEFAULT 0,
                revision INTEGER NOT NULL DEFAULT 1
            )
        """,
        "track_media": """
            CREATE TABLE IF NOT EXISTS track_media (
                track_id INTEGER PRIMARY KEY,
                sha256 VARCHAR,
                size_bytes BIGINT,
                mtime_ns BIGINT,
                volume_id VARCHAR,
                relative_path VARCHAR,
                status VARCHAR NOT NULL DEFAULT 'unknown',
                last_verified_at TIMESTAMP,
                revision INTEGER NOT NULL DEFAULT 1
            )
        """,
        "media_repair_operations": """
            CREATE TABLE IF NOT EXISTS media_repair_operations (
                id VARCHAR PRIMARY KEY,
                state VARCHAR NOT NULL,
                plan_json VARCHAR NOT NULL DEFAULT '{}',
                result_json VARCHAR NOT NULL DEFAULT '{}',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """,
        "operation_journal": """
            CREATE TABLE IF NOT EXISTS operation_journal (
                id VARCHAR PRIMARY KEY,
                kind VARCHAR NOT NULL,
                target VARCHAR NOT NULL DEFAULT '',
                state VARCHAR NOT NULL,
                progress DOUBLE NOT NULL DEFAULT 0,
                detail_json VARCHAR NOT NULL DEFAULT '{}',
                cancel_requested BOOLEAN NOT NULL DEFAULT FALSE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """,
        "track_version_groups": """
            CREATE TABLE IF NOT EXISTS track_version_groups (
                id INTEGER PRIMARY KEY DEFAULT nextval('seq_track_version_groups_id'),
                name VARCHAR,
                preferred_track_id INTEGER,
                revision INTEGER NOT NULL DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """,
        "track_version_members": """
            CREATE TABLE IF NOT EXISTS track_version_members (
                group_id INTEGER NOT NULL,
                track_id INTEGER PRIMARY KEY,
                version_label VARCHAR NOT NULL DEFAULT 'Original',
                content_label VARCHAR NOT NULL DEFAULT 'Unknown',
                note VARCHAR
            )
        """,
        "audio_presets": """
            CREATE TABLE IF NOT EXISTS audio_presets (
                id VARCHAR PRIMARY KEY,
                name VARCHAR NOT NULL,
                schema_version INTEGER NOT NULL DEFAULT 1,
                revision INTEGER NOT NULL DEFAULT 1,
                config_json VARCHAR NOT NULL,
                last_applied_at TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """,
        "controller_profiles": """
            CREATE TABLE IF NOT EXISTS controller_profiles (
                id VARCHAR PRIMARY KEY,
                name VARCHAR NOT NULL,
                adapter_id VARCHAR NOT NULL,
                schema_version INTEGER NOT NULL DEFAULT 1,
                revision INTEGER NOT NULL DEFAULT 1,
                built_in BOOLEAN NOT NULL DEFAULT FALSE,
                definition_json VARCHAR NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """,
        "controller_device_bindings": """
            CREATE TABLE IF NOT EXISTS controller_device_bindings (
                profile_id VARCHAR PRIMARY KEY,
                input_selector_json VARCHAR NOT NULL,
                output_selector_json VARCHAR,
                resolved BOOLEAN NOT NULL DEFAULT FALSE,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """,
        "usb_devices": """
            CREATE TABLE IF NOT EXISTS usb_devices (
                id VARCHAR PRIMARY KEY,
                device_identifier VARCHAR,
                volume_uuid VARCHAR,
                label VARCHAR NOT NULL,
                mount_path VARCHAR,
                filesystem VARCHAR,
                capacity_bytes BIGINT,
                free_bytes BIGINT,
                read_only BOOLEAN NOT NULL DEFAULT FALSE,
                connected BOOLEAN NOT NULL DEFAULT FALSE,
                last_seen_at TIMESTAMP
            )
        """,
        "usb_exports": """
            CREATE TABLE IF NOT EXISTS usb_exports (
                id VARCHAR PRIMARY KEY,
                usb_device_id VARCHAR,
                setlist_id INTEGER NOT NULL,
                state VARCHAR NOT NULL,
                snapshot_hash VARCHAR NOT NULL,
                snapshot_json VARCHAR NOT NULL,
                handoff_path VARCHAR,
                verification_json VARCHAR NOT NULL DEFAULT '{}',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """,
        "recording_segments": """
            CREATE TABLE IF NOT EXISTS recording_segments (
                id INTEGER PRIMARY KEY DEFAULT nextval('seq_recording_segments_id'),
                recording_id INTEGER NOT NULL,
                event_key VARCHAR NOT NULL UNIQUE,
                track_id INTEGER,
                deck VARCHAR,
                load_generation BIGINT,
                start_frame BIGINT,
                end_frame BIGINT,
                start_ms BIGINT NOT NULL,
                end_ms BIGINT,
                title_snapshot VARCHAR NOT NULL,
                artist_snapshot VARCHAR NOT NULL,
                version_snapshot VARCHAR,
                source VARCHAR NOT NULL,
                confidence VARCHAR NOT NULL DEFAULT 'confirmed',
                position INTEGER NOT NULL DEFAULT 0,
                revision INTEGER NOT NULL DEFAULT 1
            )
        """,
        "import_batches": """
            CREATE TABLE IF NOT EXISTS import_batches (
                id VARCHAR PRIMARY KEY,
                request_id VARCHAR NOT NULL UNIQUE,
                target_kind VARCHAR NOT NULL,
                target_id INTEGER,
                target_name_snapshot VARCHAR,
                origin VARCHAR NOT NULL DEFAULT 'native_file_drop',
                analysis_profile VARCHAR NOT NULL DEFAULT 'auto',
                effective_analysis_profile VARCHAR,
                state VARCHAR NOT NULL,
                paused BOOLEAN NOT NULL DEFAULT FALSE,
                cancel_requested BOOLEAN NOT NULL DEFAULT FALSE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """,
        "import_items": """
            CREATE TABLE IF NOT EXISTS import_items (
                id VARCHAR PRIMARY KEY,
                batch_id VARCHAR NOT NULL,
                input_order INTEGER NOT NULL,
                source_path VARCHAR NOT NULL,
                canonical_path VARCHAR,
                sha256 VARCHAR,
                size_bytes BIGINT,
                mtime_ns BIGINT,
                track_id INTEGER,
                state VARCHAR NOT NULL,
                load_ready BOOLEAN NOT NULL DEFAULT FALSE,
                analysis_level VARCHAR,
                error_code VARCHAR,
                error_message VARCHAR,
                attempts INTEGER NOT NULL DEFAULT 0,
                UNIQUE(batch_id, input_order)
            )
        """,
        "import_target_intents": """
            CREATE TABLE IF NOT EXISTS import_target_intents (
                item_id VARCHAR PRIMARY KEY,
                batch_id VARCHAR NOT NULL,
                target_kind VARCHAR NOT NULL,
                target_id INTEGER,
                reserved_position INTEGER,
                state VARCHAR NOT NULL,
                setlist_track_id INTEGER
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
