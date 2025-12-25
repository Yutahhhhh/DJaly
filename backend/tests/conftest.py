import os
import pytest
import sys
import tempfile
import uuid
import json
from typing import Generator
from sqlmodel import Session, create_engine
from alembic.config import Config
from alembic import command

# 1. パス解決: backendディレクトリをsys.pathに追加
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.dirname(CURRENT_DIR)
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

import infra.database.connection as db_connection
from infra.database.schema import init_raw_db
from utils.seeding import seed_initial_data

@pytest.fixture(name="session", scope="function")
def session_fixture(mocker) -> Generator[Session, None, None]:
    """
    テストごとに完全に独立したDB環境（物理ファイル）を構築する。
    DuckDBの接続競合を避けるため、単一のエンジンを Alembic と共有します。
    """
    
    # ユニークなDBファイルパスを生成
    unique_id = str(uuid.uuid4())
    test_db_path = os.path.join(tempfile.gettempdir(), f"djaly_test_{unique_id}.duckdb")
    
    # アプリケーションが参照する環境変数を上書き
    os.environ["DB_PATH"] = test_db_path
    
    # テスト用エンジンの作成 (設定を固定)
    connect_args = {'config': {'worker_threads': 4, 'access_mode': 'READ_WRITE'}}
    engine = create_engine(
        f"duckdb:///{test_db_path}",
        connect_args=connect_args
    )

    # アプリケーション全体で使用されるエンジングローバル変数をテスト用に差し替え
    db_connection.engine = engine
    db_connection.DB_PATH = test_db_path
    db_connection.DATABASE_URL = f"duckdb:///{test_db_path}"

    # 1. Raw SQLでテーブルとシーケンスを直接作成
    init_raw_db(engine)
    
    # 2. Alembicにテスト用エンジンを注入して stamp を実行
    # これにより env.py が新しいエンジンを作ろうとしてロックエラーになるのを防ぎます
    alembic_ini_path = os.path.join(BACKEND_DIR, "alembic.ini")
    alembic_cfg = Config(alembic_ini_path)
    alembic_cfg.set_main_option("script_location", os.path.join(BACKEND_DIR, "alembic"))
    
    # コネクションを再利用するように Alembic の設定にエンジンを渡す
    with engine.begin() as connection:
        alembic_cfg.attributes["connection"] = connection
        command.stamp(alembic_cfg, "head")

    # 3. アプリ起動時の init_db がテスト中に走って競合しないようモック化
    mocker.patch("infra.database.connection.init_db")

    # 4. 初期データの投入 (Prompt, Preset等)
    with Session(engine) as s:
        seed_initial_data(s)

    # テスト実行用のセッションを提供
    with Session(engine) as session:
        yield session

    # テスト終了後のクリーンアップ
    engine.dispose()
    if os.path.exists(test_db_path):
        try:
            os.remove(test_db_path)
        except OSError:
            pass

@pytest.fixture(name="client")
def client_fixture(session: Session) -> Generator:
    """FastAPIのTestClientを提供し、DBセッションをDIで差し替える"""
    from fastapi.testclient import TestClient
    from main import app
    from infra.database.connection import get_session

    def get_session_override():
        return session

    app.dependency_overrides[get_session] = get_session_override
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()

@pytest.fixture(autouse=True)
def mock_external_deps(mocker):
    """
    外部ライブラリをグローバルにモック化する。
    """
    # Essentia (音響解析ライブラリ) のモック
    mocker.patch("essentia.standard.MonoLoader")
    mocker.patch("essentia.standard.RhythmExtractor2013")
    mocker.patch("essentia.standard.KeyExtractor")
    mocker.patch("essentia.standard.RMS")
    mocker.patch("essentia.standard.Danceability")
    mocker.patch("essentia.standard.SpectralCentroidTime")
    mocker.patch("essentia.standard.ZeroCrossingRate")
    mocker.patch("essentia.standard.Spectrum")
    mocker.patch("essentia.standard.Windowing")
    mocker.patch("essentia.standard.RollOff")
    mocker.patch("essentia.standard.Flux")
    mocker.patch("essentia.standard.TensorflowPredictMusiCNN")
    mocker.patch("essentia.standard.LoudnessEBUR128")
    
    # LLM API のモック
    mock_response = mocker.MagicMock()
    mock_response.read.return_value = json.dumps({
        "choices": [{"message": {"content": '{"bpm": 120, "energy": 0.8}'}}],
        "content": [{"text": '{"genre": "House", "subgenre": "Deep House", "reason": "test", "confidence": "High"}'}],
        "candidates": [{"content": {"parts": [{"text": '{"genre": "Techno"}'}]}}]
    }).encode("utf-8")
    mocker.patch("urllib.request.urlopen", return_value=mock_response)
    
    # メタデータ抽出ライブラリのモック
    mocker.patch("tinytag.TinyTag.get")
    mocker.patch("mutagen.File")
    mocker.patch("mutagen.id3.ID3")
    mocker.patch("mutagen.mp4.MP4")
    mocker.patch("mutagen.flac.FLAC")
    
    return mock_response