from sqlmodel import create_engine, Session, text, select
from sqlalchemy.pool import QueuePool
from sqlalchemy import event
import os
import threading
from config import settings
from infra.database.schema import init_raw_db
from infra.database.compaction import ensure_healthy_db

# DBパス設定
DB_PATH = settings.DB_PATH
os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

DATABASE_URL = f"duckdb:///{DB_PATH}"

# エンジン初期化 (設定を固定)
connect_args = {'config': {'worker_threads': 4, 'access_mode': 'READ_WRITE'}}
def create_library_engine(database_url):
    # DuckDB connections must not race while opening/closing the same file.
    # Keep bounded persistent connections instead of closing on every request.
    # Multiple leases keep a slow metadata request from blocking all searches.
    db_engine = create_engine(
        database_url,
        poolclass=QueuePool,
        pool_size=8,
        max_overflow=0,
        pool_timeout=120,
        connect_args=connect_args,
    )
    open_lock = threading.Lock()

    @event.listens_for(db_engine, "do_connect")
    def serialized_connect(dialect, record, args, kwargs):
        # QueuePool can create its initial connections from several threads.
        # Serialize that lifecycle step, not SQL execution or audio inference.
        with open_lock:
            return dialect.connect(*args, **kwargs)

    return db_engine


engine = create_library_engine(DATABASE_URL)

db_lock = threading.RLock()

def init_db():
    """
    アプリケーション起動時のDB初期化フロー。
    Raw SQL + マイグレーション機能でスキーマを管理。
    """
    from utils.seeding import seed_initial_data

    with db_lock:
        try:
            # 0. SQLAlchemy エンジンが接続する前に、スキーマ移行(v4: BLOB化)や
            #    肥大ファイルのコンパクションが必要ならファイルを再構築する。
            ensure_healthy_db(DB_PATH)

            # 1. Raw SQL によるテーブル作成 + マイグレーション実行
            init_raw_db(engine)
            
            # 2. 初期データの投入
            with Session(engine) as session:
                seed_initial_data(session)
                # v0.4+: model/API credentials are owned by the MCP client.
                # Remove credentials previously stored by plumdeck.
                from app.services.setting_app_service import is_retired_llm_setting_key
                from domain.models.setting import Setting
                for saved_setting in session.exec(select(Setting)).all():
                    if is_retired_llm_setting_key(saved_setting.key):
                        session.delete(saved_setting)
                session.commit()
                
        except Exception as e:
            print(f"Error during database initialization: {e}")
            raise e

def checkpoint_db():
    """
    WAL を本体ファイルへ畳み込む。正常終了時に呼び、肥大の抑制を助ける。
    (Tauri が SIGKILL する場合は動かないため、あくまで補助。)
    """
    try:
        with db_lock:
            with engine.connect() as conn:
                conn.execute(text("CHECKPOINT"))
    except Exception as e:
        print(f"DEBUG: CHECKPOINT skipped: {e}")


def close_db():
    """
    データベース接続を終了する。
    main.py の lifespan イベントから呼び出されます。
    """
    engine.dispose()

def get_session():
    with Session(engine) as session:
        yield session

def get_setting_value(session: Session, key: str, default: str = "") -> str:
    from domain.models.setting import Setting
    try:
        setting = session.get(Setting, key)
        if setting:
            return setting.value
    except Exception as e:
        print(f"DEBUG: Error getting setting '{key}': {e}")
    return default

def set_setting_value(session: Session, key: str, value: str):
    from domain.models.setting import Setting
    try:
        setting = session.get(Setting, key)
        if not setting:
            setting = Setting(key=key, value=value)
            session.add(setting)
        else:
            setting.value = value
            session.add(setting)
        
        session.commit()
        session.refresh(setting)
        return setting
    except Exception as e:
        print(f"DEBUG: Error setting value for '{key}': {e}")
        session.rollback()
        return None
