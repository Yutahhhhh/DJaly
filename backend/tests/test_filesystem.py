import os
import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session
from models import Track

def test_stream_track(client: TestClient, session: Session, tmp_path):
    # ダミーの音声ファイルを作成
    audio_file = tmp_path / "test_audio.mp3"
    audio_file.write_bytes(b"fake audio content")
    
    # DBにトラックを登録
    track = Track(
        filepath=str(audio_file),
        title="Stream Test",
        artist="Artist",
        album="Album",
        genre="Genre",
        bpm=120,
        duration=60
    )
    session.add(track)
    session.commit()
    
    # ストリーミングAPIをコール
    # pathパラメータはURLエンコードが必要だが、TestClientが処理してくれるか確認
    # resolve_pathの挙動に依存するが、絶対パスならそのまま通るはず
    response = client.get("/api/stream", params={"path": str(audio_file)})
    assert response.status_code == 200
    assert response.content == b"fake audio content"

def test_stream_track_not_found(client: TestClient):
    response = client.get("/api/stream", params={"path": "/non/existent/file.mp3"})
    assert response.status_code == 404

def test_get_track_metadata(client: TestClient, session: Session, tmp_path):
    # ダミーファイル
    f = tmp_path / "meta.mp3"
    f.write_bytes(b"content")
    
    track = Track(
        filepath=str(f),
        title="Meta Title",
        artist="Meta Artist",
        album="Meta Album",
        genre="Meta Genre",
        bpm=120,
        duration=100
    )
    session.add(track)
    session.commit()
    
    # fs_service.get_track_metadata は内部でタグ情報を読む可能性があるため
    # 完全にテストするには tinytag をモックするか、実際のMP3を用意する必要がある
    # ここでは簡易的に 404 にならないこと、あるいはエラーハンドリングを確認する
    # 実際のファイルがMP3でないため、tinytagが失敗してNoneを返すか、
    # あるいはDBの情報だけで返す実装かによる。
    # filesystem.py を見ると fs_service.get_track_metadata を呼んでいる。
    
    # モックを使って fs_service の挙動を制御するのが安全
    # with pytest.raises(Exception): 
    #    pass

    # 今回は fs_service.get_track_metadata をモックする
    from services.filesystem import FilesystemService
    
    # MonkeyPatch
    original_method = FilesystemService.get_track_metadata
    
    def mock_get_metadata(self, session, track_id):
        if track_id == track.id:
            return {"title": "Mock Title", "artist": "Mock Artist"}
        return None
        
    FilesystemService.get_track_metadata = mock_get_metadata
    
    try:
        response = client.get("/api/metadata", params={"track_id": track.id})
        assert response.status_code == 200
        assert response.json()["title"] == "Mock Title"
        
        response = client.get("/api/metadata", params={"track_id": 9999})
        assert response.status_code == 404
    finally:
        FilesystemService.get_track_metadata = original_method

def test_list_directory(client: TestClient, session: Session, tmp_path):
    # ディレクトリ構造作成
    (tmp_path / "subdir").mkdir()
    (tmp_path / "file1.mp3").touch()
    
    # リクエスト
    response = client.post("/api/fs/list", json={"path": str(tmp_path)})
    assert response.status_code == 200
    data = response.json()
    
    filenames = [item["name"] for item in data]
    assert "subdir" in filenames
    assert "file1.mp3" in filenames
