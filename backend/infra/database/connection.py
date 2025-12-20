from sqlmodel import SQLModel, create_engine, Session
from sqlalchemy import text
from sqlalchemy.pool import QueuePool
import os
import threading
from config import settings

# DBパスは設定から取得
DB_PATH = settings.DB_PATH
os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

DATABASE_URL = f"duckdb:///{DB_PATH}"

engine = create_engine(
    DATABASE_URL, 
    pool_size=5,
    max_overflow=10,
    # 読み書きのアクセスモード設定
    connect_args={'config': {'worker_threads': 4, 'access_mode': 'READ_WRITE'}}
)

db_lock = threading.RLock()

def init_db():
    from infra.database.migrations import run_migrations
    with db_lock:
        run_migrations()

def get_session():
    with Session(engine) as session:
        yield session

def get_setting_value(session: Session, key: str, default: str = "") -> str:
    from models import Setting
    try:
        # get()はプライマリキーによる検索なので高速且つ安全
        setting = session.get(Setting, key)
        if setting:
            return setting.value
    except Exception as e:
        print(f"DEBUG: Error getting setting '{key}': {e}")
    return default

def set_setting_value(session: Session, key: str, value: str):
    """
    設定値を保存または更新する。
    ImportError解消のために追加。
    """
    from models import Setting
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