import pytest
import os
import subprocess
from fastapi.testclient import TestClient
from sqlmodel import Session
from models import Track

def test_filesystem_lyrics_artwork_endpoints(client: TestClient, session: Session, mocker):
    track = Track(filepath="/test.mp3", title="T", artist="A", album="B", genre="G", bpm=120, duration=100)
    session.add(track)
    session.commit()

    # 1. fetch_lrclib_lyrics のモック設定
    mock_lyrics = {
        "plainLyrics": "Test Lyrics",
        "syncedLyrics": "[00:01.00] Test Lyrics",
        "results": [{"artworkUrl100": "http://img.jpg"}]
    }
    mocker.patch("api.routers.metadata.fetch_lrclib_lyrics", return_value=mock_lyrics)
    
    # 2. 歌詞取得テスト
    response = client.post("/api/metadata/fetch-lyrics-single", json={"track_id": track.id})
    assert response.status_code == 200
    # syncedLyrics の内容が返ることを期待します
    assert response.json()["lyrics"] == "[00:01.00] Test Lyrics"

    # 3. アートワーク情報取得テスト
    # 内部の iTunes API 呼び出しをモック
    mock_req = mocker.patch("requests.get")
    mock_req.return_value.status_code = 200
    mock_req.return_value.json.return_value = {
        "resultCount": 1, 
        "results": [{"artworkUrl100": "http://img.jpg"}]
    }
    
    response = client.post("/api/metadata/fetch-artwork-info", json={"track_id": track.id})
    assert response.status_code == 200

def test_genres_batch_llm_analyze(client: TestClient, session: Session, mocker):
    t1 = Track(filepath="/1.mp3", title="T1", artist="A1", album="B", genre="Unknown", bpm=120, duration=100)
    session.add(t1)
    session.commit()

    # ID|Genre 形式のレスポンスをシミュレート
    mocker.patch("app.services.genre_app_service.generate_text", return_value=f"{t1.id}|Deep House")
    
    response = client.post("/api/genres/batch-llm-analyze", json={"track_ids": [t1.id], "mode": "genre"})
    assert response.status_code == 200
    assert response.json()[0]["new_genre"] == "Deep House"

def test_system_save_and_reveal(client: TestClient, tmp_path, mocker):
    # ファイル保存テスト
    path = str(tmp_path / "test.txt")
    res = client.post("/api/system/save-file", json={"path": path, "content": "hello"})
    assert res.status_code == 200
    assert os.path.exists(path)

    # OSファイルマネージャー表示テスト
    mock_run = mocker.patch("subprocess.run")
    client.post("/api/system/reveal-file", json={"path": path})
    assert mock_run.called

def test_settings_import_presets(client: TestClient, session: Session):
    csv_content = "name,description,preset_type,prompt_content\nNewPre,Desc,all,Be a DJ"
    files = {"file": ("presets.csv", csv_content, "text/csv")}
    
    # 解析フェーズ
    res = client.post("/api/settings/presets/import/analyze", files=files)
    assert res.status_code == 200
    data = res.json()
    
    # 実行フェーズ
    exec_req = {"new_presets": data["new_presets"], "updates": []}
    res = client.post("/api/settings/presets/import/execute", json=exec_req)
    assert res.status_code == 200
    assert res.json()["imported"] == 1