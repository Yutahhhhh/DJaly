from sqlalchemy import text
from sqlalchemy.engine import Engine
from utils.logger import get_logger

logger = get_logger(__name__)

# 現在のスキーマバージョン
CURRENT_SCHEMA_VERSION = 1

def get_db_schema_sql() -> str:
    """
    DuckDBの制約回避：
    DuckDBでは外部キー(FK)が設定されているテーブルの更新(UPDATE)が失敗しやすいため、
    物理的な FOREIGN KEY 句を削除し、インデックスと主キーのみで構成します。
    """
    return """
    CREATE SEQUENCE IF NOT EXISTS seq_tracks_id START 1;
    CREATE SEQUENCE IF NOT EXISTS seq_setlists_id START 1;
    CREATE SEQUENCE IF NOT EXISTS seq_prompts_id START 1;
    CREATE SEQUENCE IF NOT EXISTS seq_presets_id START 1;
    CREATE SEQUENCE IF NOT EXISTS seq_setlist_tracks_id START 1;

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
    );

    CREATE TABLE IF NOT EXISTS track_analyses (
        track_id INTEGER PRIMARY KEY,
        beat_positions JSON,
        waveform_peaks JSON,
        features_extra_json VARCHAR DEFAULT '{}'
    );

    CREATE TABLE IF NOT EXISTS track_embeddings (
        track_id INTEGER PRIMARY KEY,
        model_name VARCHAR DEFAULT 'musicnn',
        embedding_json VARCHAR DEFAULT '[]',
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS lyrics (
        track_id INTEGER PRIMARY KEY,
        content VARCHAR DEFAULT '',
        source VARCHAR DEFAULT 'user',
        language VARCHAR,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS prompts (
        id INTEGER PRIMARY KEY DEFAULT nextval('seq_prompts_id'),
        name VARCHAR NOT NULL,
        content VARCHAR NOT NULL,
        is_default BOOLEAN DEFAULT FALSE,
        display_order INTEGER DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS presets (
        id INTEGER PRIMARY KEY DEFAULT nextval('seq_presets_id'),
        name VARCHAR NOT NULL,
        description VARCHAR,
        preset_type VARCHAR DEFAULT 'all',
        filters_json VARCHAR DEFAULT '{}',
        prompt_id INTEGER,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

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
    );

    CREATE TABLE IF NOT EXISTS setlist_tracks (
        id INTEGER PRIMARY KEY DEFAULT nextval('seq_setlist_tracks_id'),
        setlist_id INTEGER NOT NULL,
        track_id INTEGER NOT NULL,
        position INTEGER NOT NULL,
        transition_note VARCHAR,
        wordplay_json VARCHAR,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS settings (
        key VARCHAR PRIMARY KEY,
        value VARCHAR NOT NULL
    );

    CREATE TABLE IF NOT EXISTS schema_info (
        key VARCHAR PRIMARY KEY,
        value VARCHAR NOT NULL
    );
    """

def get_current_schema_version(conn) -> int:
    try:
        result = conn.execute(text("SELECT value FROM schema_info WHERE key = 'version'"))
        row = result.fetchone()
        return int(row[0]) if row else 0
    except Exception: return 0

def set_schema_version(conn, version: int):
    conn.execute(text("""
        INSERT INTO schema_info (key, value) VALUES ('version', :version)
        ON CONFLICT (key) DO UPDATE SET value = :version
    """), {"version": str(version)})

def init_raw_db(conn_engine: Engine):
    logger.info("Initializing DuckDB schema...")
    try:
        with conn_engine.begin() as conn:
            statements = [s.strip() for s in get_db_schema_sql().split(';') if s.strip()]
            for stmt in statements:
                conn.execute(text(stmt))
            
            current_version = get_current_schema_version(conn)
            if current_version < CURRENT_SCHEMA_VERSION:
                set_schema_version(conn, CURRENT_SCHEMA_VERSION)
    except Exception as e:
        logger.error(f"Failed to initialize database schema: {e}")
        raise e