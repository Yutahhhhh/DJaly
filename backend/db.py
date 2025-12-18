from sqlmodel import SQLModel, create_engine, Session
from sqlalchemy import text
from sqlalchemy.pool import NullPool
import os
import sys
import threading
import platformdirs

# --- Path Logic Modification for Native App ---
APP_NAME = "Djaly"
APP_AUTHOR = "DjalyDev"

# macOS: ~/Library/Application Support/Djaly
# Windows: C:\Users\<User>\AppData\Local\DjalyDev\Djaly
# Linux: ~/.local/share/Djaly
user_data_dir = platformdirs.user_data_dir(APP_NAME, APP_AUTHOR)
os.makedirs(user_data_dir, exist_ok=True)

# DBファイルをユーザーデータディレクトリに配置
DB_PATH = os.path.join(user_data_dir, "djaly.duckdb")
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