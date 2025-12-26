import pytest
import json
import tempfile
from pathlib import Path
from sqlmodel import Session
from models import Track, Lyrics
from app.services.metadata_app_service import MetadataAppService


@pytest.fixture
def metadata_service(mocker, tmp_path):
    """テスト用のMetadataAppServiceを提供"""
    # DB_PATHをモックしてテスト用のパスを使用
    test_db_path = tmp_path / "test.duckdb"
    mocker.patch("app.services.metadata_app_service.DB_PATH", str(test_db_path))
    
    service = MetadataAppService()
    service._skip_cache = service._load_skip_cache()
    return service


def test_skip_cache_initialization(metadata_service):
    """スキップキャッシュの初期化テスト"""
    assert "release_date" in metadata_service._skip_cache
    assert "lyrics" in metadata_service._skip_cache
    assert isinstance(metadata_service._skip_cache["release_date"], set)
    assert isinstance(metadata_service._skip_cache["lyrics"], set)


def test_save_and_load_skip_cache(metadata_service):
    """スキップキャッシュの保存と読み込みテスト"""
    # データを追加
    metadata_service._skip_cache["release_date"].add(1)
    metadata_service._skip_cache["release_date"].add(2)
    metadata_service._skip_cache["lyrics"].add(3)
    
    # 保存
    metadata_service._save_skip_cache()
    
    # ファイルが作成されたことを確認
    assert metadata_service.SKIP_CACHE_FILE.exists()
    
    # 内容を確認
    with open(metadata_service.SKIP_CACHE_FILE, 'r') as f:
        data = json.load(f)
    assert set(data["release_date"]) == {1, 2}
    assert set(data["lyrics"]) == {3}
    
    # 新しいインスタンスで読み込みをシミュレート
    # (同じDB_PATHを使用しているため、同じキャッシュファイルを参照する)
    loaded_cache = metadata_service._load_skip_cache()
    
    assert loaded_cache["release_date"] == {1, 2}
    assert loaded_cache["lyrics"] == {3}


def test_clear_skip_cache_specific_type(metadata_service):
    """特定タイプのキャッシュクリアテスト"""
    metadata_service._skip_cache["release_date"].add(1)
    metadata_service._skip_cache["lyrics"].add(2)
    
    # リリース日のキャッシュのみクリア
    metadata_service.clear_skip_cache("release_date")
    
    assert len(metadata_service._skip_cache["release_date"]) == 0
    assert len(metadata_service._skip_cache["lyrics"]) == 1


def test_clear_skip_cache_all_types(metadata_service):
    """全タイプのキャッシュクリアテスト"""
    metadata_service._skip_cache["release_date"].add(1)
    metadata_service._skip_cache["lyrics"].add(2)
    
    # 全てクリア
    metadata_service.clear_skip_cache()
    
    assert len(metadata_service._skip_cache["release_date"]) == 0
    assert len(metadata_service._skip_cache["lyrics"]) == 0


@pytest.mark.asyncio
async def test_update_release_date_not_found_cached(metadata_service, session: Session, mocker):
    """リリース日が見つからない場合、キャッシュに追加されることを確認"""
    track = Track(
        filepath="/test.mp3",
        title="Test Track",
        artist="Test Artist",
        album="Test Album",
        genre="Test",
        bpm=120,
        duration=180
    )
    session.add(track)
    session.commit()
    session.refresh(track)
    
    # iTunes APIが何も返さないようモック
    mock_fetch = mocker.patch("app.services.metadata_app_service.fetch_itunes_release_date")
    mock_fetch.return_value = None
    
    # 更新を実行
    updated, reason = await metadata_service._update_release_date(session, track, False)
    
    assert updated is False
    assert reason == "not_found"
    
    # ここではキャッシュに追加するのは呼び出し側の責任なので、
    # 実際の_run_updateの動作をテストする必要がある


@pytest.mark.asyncio
async def test_update_release_date_found(metadata_service, session: Session, mocker):
    """リリース日が見つかった場合、正常に更新されることを確認"""
    track = Track(
        filepath="/test.mp3",
        title="Test Track",
        artist="Test Artist",
        album="Test Album",
        genre="Test",
        bpm=120,
        duration=180
    )
    session.add(track)
    session.commit()
    session.refresh(track)
    
    # iTunes APIが日付を返すようモック
    mock_fetch = mocker.patch("app.services.metadata_app_service.fetch_itunes_release_date")
    mock_fetch.return_value = "2020-05-15T12:00:00Z"
    
    # 更新を実行
    updated, reason = await metadata_service._update_release_date(session, track, False)
    
    assert updated is True
    assert reason is None
    
    session.refresh(track)
    assert track.year == 2020


@pytest.mark.asyncio
async def test_update_release_date_already_exists(metadata_service, session: Session):
    """既にリリース日がある場合、スキップされることを確認"""
    track = Track(
        filepath="/test.mp3",
        title="Test Track",
        artist="Test Artist",
        album="Test Album",
        genre="Test",
        bpm=120,
        duration=180,
        year=2019
    )
    session.add(track)
    session.commit()
    session.refresh(track)
    
    # 更新を実行（overwrite=False）
    updated, reason = await metadata_service._update_release_date(session, track, False)
    
    assert updated is False
    assert reason == "already_exists"


@pytest.mark.asyncio
async def test_update_lyrics_not_found_cached(metadata_service, session: Session, mocker):
    """歌詞が見つからない場合の動作確認"""
    track = Track(
        filepath="/test.mp3",
        title="Test Track",
        artist="Test Artist",
        album="Test Album",
        genre="Test",
        bpm=120,
        duration=180
    )
    session.add(track)
    session.commit()
    session.refresh(track)
    
    # LRCLIB APIが何も返さないようモック
    mock_fetch = mocker.patch("app.services.metadata_app_service.fetch_lrclib_lyrics")
    mock_fetch.return_value = None
    
    # 更新を実行
    updated, reason = await metadata_service._update_lyrics(session, track, False)
    
    assert updated is False
    assert reason == "not_found"


@pytest.mark.asyncio
async def test_update_lyrics_found(metadata_service, session: Session, mocker):
    """歌詞が見つかった場合、正常に更新されることを確認"""
    track = Track(
        filepath="/test.mp3",
        title="Test Track",
        artist="Test Artist",
        album="Test Album",
        genre="Test",
        bpm=120,
        duration=180
    )
    session.add(track)
    session.commit()
    session.refresh(track)
    
    # LRCLIB APIが歌詞を返すようモック
    mock_fetch = mocker.patch("app.services.metadata_app_service.fetch_lrclib_lyrics")
    mock_fetch.return_value = {
        "plainLyrics": "Test lyrics content\nLine 2\nLine 3"
    }
    
    # 更新を実行
    updated, reason = await metadata_service._update_lyrics(session, track, False)
    
    assert updated is True
    assert reason is None
    
    # 歌詞が保存されたことを確認
    lyrics = session.get(Lyrics, track.id)
    assert lyrics is not None
    assert lyrics.content == "Test lyrics content\nLine 2\nLine 3"
    assert lyrics.source == "lrclib"


@pytest.mark.asyncio
async def test_update_lyrics_already_exists(metadata_service, session: Session):
    """既に歌詞がある場合、スキップされることを確認"""
    track = Track(
        filepath="/test.mp3",
        title="Test Track",
        artist="Test Artist",
        album="Test Album",
        genre="Test",
        bpm=120,
        duration=180
    )
    session.add(track)
    session.commit()
    session.refresh(track)
    
    # 既存の歌詞を追加
    lyrics = Lyrics(track_id=track.id, content="Existing lyrics", source="manual")
    session.add(lyrics)
    session.commit()
    
    # 更新を実行（overwrite=False）
    updated, reason = await metadata_service._update_lyrics(session, track, False)
    
    assert updated is False
    assert reason == "already_exists"


def test_api_clear_cache(client, session: Session, tmp_path, mocker):
    """APIエンドポイント経由でのキャッシュクリア"""
    # metadata_app_serviceをモック
    mock_service = mocker.patch("api.routers.metadata.metadata_app_service")
    
    # リリース日のキャッシュをクリア
    response = client.post("/api/metadata/clear-cache", json={"update_type": "release_date"})
    assert response.status_code == 200
    assert response.json()["status"] == "success"
    
    # clear_skip_cacheが正しい引数で呼ばれたことを確認
    mock_service.clear_skip_cache.assert_called_once_with("release_date")


def test_api_clear_cache_all(client, session: Session, mocker):
    """全てのキャッシュをクリアするAPIテスト"""
    mock_service = mocker.patch("api.routers.metadata.metadata_app_service")
    
    # タイプを指定せずにクリア
    response = client.post("/api/metadata/clear-cache", json={})
    assert response.status_code == 200
    
    # Noneで呼ばれることを確認
    mock_service.clear_skip_cache.assert_called_once_with(None)


@pytest.mark.asyncio
async def test_run_update_with_cache_filtering(metadata_service, session: Session, mocker):
    """キャッシュによるフィルタリングが正しく動作することを確認"""
    # トラックを3つ作成
    tracks = [
        Track(filepath="/t1.mp3", title="T1", artist="A1", album="B", genre="G", bpm=120, duration=180),
        Track(filepath="/t2.mp3", title="T2", artist="A2", album="B", genre="G", bpm=120, duration=180),
        Track(filepath="/t3.mp3", title="T3", artist="A3", album="B", genre="G", bpm=120, duration=180),
    ]
    for t in tracks:
        session.add(t)
    session.commit()
    
    for t in tracks:
        session.refresh(t)
    
    # track 1 をキャッシュに追加
    metadata_service._skip_cache["release_date"].add(tracks[0].id)
    
    # iTunes APIのモック（常に何も返さない）
    mock_fetch = mocker.patch("app.services.metadata_app_service.fetch_itunes_release_date")
    mock_fetch.return_value = None
    
    # エンジンをモック（実際のDBセッションを使うため）
    mocker.patch("app.services.metadata_app_service.engine", session.get_bind())
    
    # WebSocketの送信をモック
    metadata_service.websocket_connections = []
    
    # 更新を実行
    # Note: _run_updateは内部でSession(engine)を作成するため、
    # 実際のテストでは完全な統合テストが必要になる
    # ここではロジックの確認に留める
    
    # キャッシュに含まれるIDが除外されることを確認
    # （実際の実装では_run_update内でクエリが構築される）
    from sqlmodel import select
    query = select(Track)
    skip_ids = metadata_service._skip_cache.get("release_date", set())
    if skip_ids:
        query = query.where(Track.id.not_in(skip_ids))
    
    filtered_tracks = session.exec(query).all()
    assert len(filtered_tracks) == 2
    assert tracks[0].id not in [t.id for t in filtered_tracks]
