from sqlmodel import create_engine, Session, text
import os
import threading
from config import settings
from infra.database.schema import init_raw_db

# DBパス設定
DB_PATH = settings.DB_PATH
os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

DATABASE_URL = f"duckdb:///{DB_PATH}"

# エンジン初期化 (設定を固定)
connect_args = {'config': {'worker_threads': 4, 'access_mode': 'READ_WRITE'}}
engine = create_engine(
    DATABASE_URL, 
    pool_size=5,
    max_overflow=10,
    connect_args=connect_args
)

db_lock = threading.RLock()

def init_db():
    """
    アプリケーション起動時のDB初期化フロー。
    DuckDBの接続競合を避けるため、単一のコネクションを Alembic と共有します。
    """
    from alembic.config import Config
    from alembic import command
    from utils.seeding import seed_initial_data
    
    # DBが新規作成かどうかを事前にチェック
    is_new_db = not os.path.exists(DB_PATH) or os.path.getsize(DB_PATH) == 0

    with db_lock:
        try:
            # 1. Raw SQL によるテーブルとシーケンスの作成
            init_raw_db(engine)

            # 2. Alembicマイグレーションの実行
            base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            alembic_ini_path = os.path.join(base_dir, "alembic.ini")
            alembic_cfg = Config(alembic_ini_path)
            alembic_cfg.set_main_option("script_location", os.path.join(base_dir, "alembic"))
            
            # DuckDBのロックエラーを避けるため、既存のコネクションをAlembicに渡す
            with engine.begin() as connection:
                alembic_cfg.attributes["connection"] = connection
                
                if is_new_db:
                    # 新規DBなら現在のバージョンをスタンプ
                    print("New database detected. Stamping version...")
                    command.stamp(alembic_cfg, "head")
                else:
                    # 既存DBなら差分を適用
                    print("Existing database detected. Running migrations...")
                    command.upgrade(alembic_cfg, "head")
            
            # 3. 初期データの投入
            with Session(engine) as session:
                seed_initial_data(session)
                
        except Exception as e:
            print(f"Error during database initialization: {e}")
            raise e

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