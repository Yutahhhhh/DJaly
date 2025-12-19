from sqlmodel import SQLModel, create_engine, Session
from sqlalchemy import text
from sqlalchemy.pool import NullPool
import os
import sys
import threading
from config import settings

# DBパスは設定から取得
DB_PATH = settings.DB_PATH
# ディレクトリが存在しない場合は作成 (DB_PATHの親ディレクトリ)
os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

DATABASE_URL = f"duckdb:///{DB_PATH}"

# poolclass=NullPool is crucial for DuckDB locking issues
# 本番ビルドではSQLログ(echo)を無効化
engine = create_engine(DATABASE_URL, poolclass=NullPool, echo=False)
print(f"DEBUG: DB_PATH used: {DB_PATH}")

db_lock = threading.RLock()

def init_db():
    from migrations import run_migrations
    
    with db_lock:
        run_migrations()

def get_session():
    with Session(engine) as session:
        yield session

# Circular import回避のためのHelper
def get_setting_value(session: Session, key: str, default: str = "") -> str:
    from models import Setting
    setting = session.get(Setting, key)
    if setting:
        return setting.value
    return default

def set_setting_value(session: Session, key: str, value: str):
    from models import Setting
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