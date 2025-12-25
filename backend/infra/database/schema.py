from sqlalchemy import text
from sqlalchemy.engine import Engine
from utils.logger import get_logger

logger = get_logger(__name__)

# 現在のスキーマバージョン（新しいマイグレーションを追加するたびにインクリメント）
CURRENT_SCHEMA_VERSION = 1

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

    CREATE TABLE IF NOT EXISTS schema_info (
        key VARCHAR PRIMARY KEY,
        value VARCHAR NOT NULL
    );
    """

def get_migrations() -> dict[int, list[str]]:
    """
    スキーマバージョンごとのマイグレーションSQLを定義。
    キーはターゲットバージョン、値はそのバージョンに上げるためのSQL文のリスト。
    
    例: バージョン1から2に上げる場合、migrations[2] のSQLが実行される。
    
    新しいマイグレーションを追加する場合:
    1. CURRENT_SCHEMA_VERSION をインクリメント
    2. 新しいバージョン番号をキーとしてSQLを追加
    """
    return {
        # 例: バージョン2へのマイグレーション
        # 2: [
        #     "ALTER TABLE tracks ADD COLUMN IF NOT EXISTS new_column VARCHAR DEFAULT ''",
        # ],
    }

def get_current_schema_version(conn) -> int:
    """schema_infoテーブルから現在のスキーマバージョンを取得"""
    try:
        result = conn.execute(text("SELECT value FROM schema_info WHERE key = 'version'"))
        row = result.fetchone()
        if row:
            return int(row[0])
    except Exception:
        pass
    return 0  # 初回起動時やschema_infoテーブルがない場合

def set_schema_version(conn, version: int):
    """スキーマバージョンをschema_infoテーブルに保存"""
    conn.execute(text("""
        INSERT INTO schema_info (key, value) VALUES ('version', :version)
        ON CONFLICT (key) DO UPDATE SET value = :version
    """), {"version": str(version)})

def run_migrations(conn, from_version: int, to_version: int):
    """指定されたバージョン範囲のマイグレーションを実行"""
    migrations = get_migrations()
    
    for version in range(from_version + 1, to_version + 1):
        if version in migrations:
            logger.info(f"Running migration to version {version}...")
            for sql in migrations[version]:
                try:
                    conn.execute(text(sql))
                    logger.info(f"  Executed: {sql[:80]}...")
                except Exception as e:
                    logger.error(f"  Failed: {sql[:80]}... Error: {e}")
                    raise e
            logger.info(f"Migration to version {version} completed.")

def init_raw_db(conn_engine: Engine):
    """
    Raw SQLを実行してDBを初期化する。
    1. 基本スキーマの作成（CREATE TABLE IF NOT EXISTS）
    2. スキーマバージョンのチェックとマイグレーション実行
    """
    logger.info("Initializing DuckDB schema with Raw SQL...")
    try:
        with conn_engine.begin() as conn:
            # 1. 基本スキーマの作成
            statements = [s.strip() for s in get_db_schema_sql().split(';') if s.strip()]
            for stmt in statements:
                conn.execute(text(stmt))
            
            # 2. スキーマバージョンのチェックとマイグレーション
            current_version = get_current_schema_version(conn)
            
            if current_version < CURRENT_SCHEMA_VERSION:
                logger.info(f"Schema upgrade needed: v{current_version} -> v{CURRENT_SCHEMA_VERSION}")
                run_migrations(conn, current_version, CURRENT_SCHEMA_VERSION)
                set_schema_version(conn, CURRENT_SCHEMA_VERSION)
                logger.info(f"Schema upgraded to version {CURRENT_SCHEMA_VERSION}")
            elif current_version == 0:
                # 新規DB: バージョンを設定
                set_schema_version(conn, CURRENT_SCHEMA_VERSION)
                logger.info(f"New database initialized with schema version {CURRENT_SCHEMA_VERSION}")
            else:
                logger.info(f"Schema is up to date (version {current_version})")
                
        logger.info("Database schema initialized successfully.")
    except Exception as e:
        logger.error(f"Failed to initialize database schema: {e}")
        raise e