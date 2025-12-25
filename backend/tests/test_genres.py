import pytest
from sqlmodel import Session, text, delete
from models import Track
from fastapi.testclient import TestClient

def test_get_all_genres(client: TestClient, session: Session):
    t1 = Track(filepath="/1.mp3", title="T1", artist="A", album="B", genre="Techno", bpm=120, duration=100)
    t2 = Track(filepath="/2.mp3", title="T2", artist="A", album="B", genre="House", bpm=120, duration=100)
    session.add(t1)
    session.add(t2)
    session.commit()
    
    response = client.get("/api/genres/list")
    assert response.status_code == 200
    genres = response.json()
    assert "Techno" in genres
    assert "House" in genres

def test_get_unknown_tracks(client: TestClient, session: Session):
    # 既存データをクリア
    session.exec(delete(Track))
    session.commit()

    t1 = Track(filepath="/u1.mp3", title="U1", artist="A", album="B", genre="Unknown", bpm=120, duration=100)
    t2 = Track(filepath="/u2.mp3", title="U2", artist="A", album="B", genre="", bpm=120, duration=100)
    t3 = Track(filepath="/k1.mp3", title="K1", artist="A", album="B", genre="Known", bpm=120, duration=100, is_genre_verified=True)
    session.add(t1)
    session.add(t2)
    session.add(t3)
    session.commit()
    
    response = client.get("/api/genres/unknown")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2
    titles = [t["title"] for t in data]
    assert "U1" in titles
    assert "U2" in titles

def test_get_unknown_tracks_subgenre_mode(client: TestClient, session: Session):
    session.exec(delete(Track))
    session.commit()

    # T1: Verified Genre, No Subgenre -> Should appear in subgenre mode
    t1 = Track(filepath="/s1.mp3", title="S1", artist="A", album="B", genre="Techno", subgenre="", bpm=120, duration=100, is_genre_verified=True)
    # T2: Verified Genre, Has Subgenre -> Should NOT appear
    t2 = Track(filepath="/s2.mp3", title="S2", artist="A", album="B", genre="Techno", subgenre="Minimal", bpm=120, duration=100, is_genre_verified=True)
    # T3: Unverified Genre -> Should appear (if we consider unverified genre implies unknown subgenre? Or strictly empty subgenre?)
    # Our logic is: subgenre == None or subgenre == ""
    t3 = Track(filepath="/s3.mp3", title="S3", artist="A", album="B", genre="Unknown", subgenre="", bpm=120, duration=100, is_genre_verified=False)

    session.add(t1)
    session.add(t2)
    session.add(t3)
    session.commit()
    
    response = client.get("/api/genres/unknown?mode=subgenre")
    assert response.status_code == 200
    data = response.json()
    
    titles = [t["title"] for t in data]
    assert "S1" in titles
    assert "S3" in titles
    assert "S2" not in titles

def test_llm_analyze(client: TestClient, session: Session, mocker):
    # LLMのモックはconftest.pyで行われているが、
    # GenreService内でgenerate_textの結果をパースするロジックがあるため、
    # 適切なJSONを返すように調整が必要かもしれない。
    # conftest.pyのmock_llmはvibe parameters用のJSONを返している。
    # GenreServiceが期待するのはジャンル文字列やJSONなど。
    
    # GenreService.analyze_track_with_llmの実装を見ると、
    # generate_textの結果をパースしてジャンルを抽出しているはず。
    # ここでは特定のレスポンスを返すようにモックを上書きする。
    
    mock_gen = mocker.patch("app.services.genre_app_service.generate_text")
    mock_gen.return_value = '{"genre": "Techno", "subgenre": "Minimal Techno", "reason": "It sounds minimal.", "confidence": "High"}'
    
    t1 = Track(filepath="/l1.mp3", title="L1", artist="A", album="B", genre="Unknown", bpm=120, duration=100)
    session.add(t1)
    session.commit()
    
    response = client.post("/api/genres/llm-analyze", json={"track_id": t1.id})
    assert response.status_code == 200
    data = response.json()
    assert data["genre"] == "Techno"
    assert data["subgenre"] == "Minimal Techno"
    
    session.refresh(t1)
    assert t1.genre == "Techno"
    assert t1.subgenre == "Minimal Techno"

def test_batch_update_genres(client: TestClient, session: Session):
    # GenreBatchUpdateRequest: parent_track_idのジャンルをtarget_track_idsに適用する
    t1 = Track(filepath="/b1.mp3", title="Source", artist="A", album="B", genre="New Genre", subgenre="New Sub", bpm=120, duration=100)
    t2 = Track(filepath="/b2.mp3", title="Target", artist="A", album="B", genre="Old Genre", subgenre="Old Sub", bpm=120, duration=100)
    session.add(t1)
    session.add(t2)
    session.commit()
    
    response = client.post("/api/genres/batch-update", json={
        "parent_track_id": t1.id,
        "target_track_ids": [t2.id]
    })
    assert response.status_code == 200
    
    session.refresh(t2)
    assert t2.genre == "New Genre"
    assert t2.subgenre == "New Sub"

def test_get_cleanup_suggestions_mode(client: TestClient, session: Session):
    session.exec(delete(Track))
    session.commit()
    
    # Genre inconsistencies
    t1 = Track(filepath="/1.mp3", title="T1", artist="A", album="B", genre="Hip-Hop", subgenre="Trap", bpm=120, duration=100)
    t2 = Track(filepath="/2.mp3", title="T2", artist="A", album="B", genre="Hip Hop", subgenre="Trap", bpm=120, duration=100)
    
    # Subgenre inconsistencies
    t3 = Track(filepath="/3.mp3", title="T3", artist="A", album="B", genre="Techno", subgenre="Hard Techno", bpm=120, duration=100)
    t4 = Track(filepath="/4.mp3", title="T4", artist="A", album="B", genre="Techno", subgenre="Hard-Techno", bpm=120, duration=100)
    
    session.add(t1)
    session.add(t2)
    session.add(t3)
    session.add(t4)
    session.commit()
    
    # Test Genre Mode (Default)
    response = client.get("/api/genres/cleanup-suggestions?mode=genre")
    assert response.status_code == 200
    data = response.json()
    # Should find Hip-Hop vs Hip Hop
    assert len(data) >= 1
    found_genre = any(g["primary_genre"] in ["Hip Hop", "Hip-Hop"] for g in data)
    assert found_genre
    
    # Test Subgenre Mode
    response = client.get("/api/genres/cleanup-suggestions?mode=subgenre")
    assert response.status_code == 200
    data = response.json()
    # Should find Hard Techno vs Hard-Techno
    assert len(data) >= 1
    found_subgenre = any(g["primary_genre"] in ["Hard Techno", "Hard-Techno"] for g in data)
    assert found_subgenre

