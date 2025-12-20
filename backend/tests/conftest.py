import os
import pytest
import tempfile
import sys
import json
from typing import Generator
from fastapi.testclient import TestClient
from sqlmodel import Session, create_engine, text, delete
from sqlalchemy.pool import StaticPool

# Ensure backend directory is in sys.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# テスト実行前に環境変数を書き換え
TEST_DB_FILE = os.path.join(tempfile.gettempdir(), "djaly_test.duckdb")
os.environ["DB_PATH"] = TEST_DB_FILE
os.environ["DJALY_LOG_DIR"] = tempfile.gettempdir()

# Pydantic V2 警告抑制のための設定
import warnings
warnings.filterwarnings("ignore", category=DeprecationWarning)

from main import app
from db import get_session, engine as prod_engine
import db
import migrations
from models import Track, TrackAnalysis, Setlist, SetlistTrack, Preset, Prompt, Setting

# テスト用のエンジン（StaticPoolを使用して、単一の接続を全テストで共有）
test_engine = create_engine(
    f"duckdb:///{TEST_DB_FILE}",
    poolclass=StaticPool
)

@pytest.fixture(name="session", scope="function")
def session_fixture() -> Generator[Session, None, None]:
    """テストごとにマイグレーション済みのクリーンなセッションを提供"""
    # Patch engines
    original_db_engine = db.engine
    db.engine = test_engine
    migrations.engine = test_engine

    # テーブルとシーケンスの初期化
    migrations.run_migrations()

    with Session(test_engine) as session:
        # 全テーブルのデータをクリアしてクリーンな状態にする
        session.exec(delete(SetlistTrack))
        session.exec(delete(Setlist))
        session.exec(delete(TrackAnalysis))
        session.exec(delete(Track))
        session.exec(delete(Preset))
        session.exec(delete(Prompt))
        session.exec(delete(Setting))
        session.commit()
        yield session

    db.engine = original_db_engine

@pytest.fixture(name="client")
def client_fixture(session: Session) -> Generator[TestClient, None, None]:
    """Dependency Injectionを差し替えてTestClientを生成"""
    def get_session_override():
        return session

    app.dependency_overrides[get_session] = get_session_override
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()

@pytest.fixture(autouse=True)
def mock_external_deps(mocker):
    """ライブラリの重い処理や外部通信をデフォルトでモック"""
    # Essentia モック
    mocker.patch("essentia.standard.MonoLoader")
    mocker.patch("essentia.standard.RhythmExtractor2013")
    mocker.patch("essentia.standard.KeyExtractor")
    
    # LLM モック (urllib.request)
    mock_response = mocker.MagicMock()
    mock_response.read.return_value = json.dumps({
        "choices": [{"message": {"content": '{"bpm": 120, "energy": 0.5}'}}],
        "content": [{"text": '{"genre": "House"}'}],
        "candidates": [{"content": {"parts": [{"text": "result"}]}}]
    }).encode("utf-8")
    # MagicMock handles __enter__ automatically
    mocker.patch("urllib.request.urlopen", return_value=mock_response)
    
    # Mutagen/TinyTag モック
    mocker.patch("tinytag.TinyTag.get")
    mocker.patch("mutagen.File")
    
    return mock_response
