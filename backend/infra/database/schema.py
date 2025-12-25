from sqlalchemy import text
from sqlalchemy.engine import Engine
from utils.logger import get_logger

logger = get_logger(__name__)

def get_db_schema_sql() -> str:
    """
    Infrastructure Layer: DuckDB Physical Schema Definition.
    DuckDBの制約に対応するため、SEQUENCEとTABLEをRaw SQLで手動定義します。
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
    """

def init_raw_db(conn_engine: Engine):
    """Raw SQLを実行してDBを初期化する。Engine.begin()を使用し確実にコミットする。"""
    logger.info("Initializing DuckDB schema with Raw SQL...")
    try:
        with conn_engine.begin() as conn: # begin() は自動的に COMMIT/ROLLBACK を行う
            # セミコロンで分割して実行（DuckDB/SQLAlchemyの制約対策）
            statements = [s.strip() for s in get_db_schema_sql().split(';') if s.strip()]
            for stmt in statements:
                conn.execute(text(stmt))
        logger.info("Database schema initialized successfully.")
    except Exception as e:
        logger.error(f"Failed to initialize database schema: {e}")
        raise e