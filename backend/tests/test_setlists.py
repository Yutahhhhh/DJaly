import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session
from models import Setlist, Track, SetlistTrack

def test_create_setlist(client: TestClient, session: Session):
    response = client.post("/api/setlists", json={"name": "My Setlist"})
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "My Setlist"

def test_get_setlists(client: TestClient, session: Session):
    s1 = Setlist(name="S1")
    session.add(s1)
    session.commit()
    
    response = client.get("/api/setlists")
    assert response.status_code == 200
    names = [s["name"] for s in response.json()]
    assert "S1" in names

def test_update_setlist(client: TestClient, session: Session):
    s1 = Setlist(name="Old S")
    session.add(s1)
    session.commit()
    
    response = client.put(f"/api/setlists/{s1.id}", json={"name": "New S"})
    assert response.status_code == 200
    assert response.json()["name"] == "New S"

def test_delete_setlist(client: TestClient, session: Session):
    s1 = Setlist(name="Del S")
    session.add(s1)
    session.commit()
    
    response = client.delete(f"/api/setlists/{s1.id}")
    assert response.status_code == 200
    assert session.get(Setlist, s1.id) is None

def test_setlist_tracks(client: TestClient, session: Session):
    s1 = Setlist(name="S Tracks")
    t1 = Track(filepath="/t1.mp3", title="T1", artist="A", album="B", genre="G", bpm=120, duration=100)
    t2 = Track(filepath="/t2.mp3", title="T2", artist="A", album="B", genre="G", bpm=120, duration=100)
    session.add(s1)
    session.add(t1)
    session.add(t2)
    session.commit()
    
    # Update tracks
    response = client.post(f"/api/setlists/{s1.id}/tracks", json=[t1.id, t2.id])
    assert response.status_code == 200
    
    # Get tracks
    response = client.get(f"/api/setlists/{s1.id}/tracks")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2
    assert data[0]["title"] == "T1"

def test_export_m3u8(client: TestClient, session: Session):
    s1 = Setlist(name="ExportSet")
    t1 = Track(filepath="/music/song.mp3", title="Song", artist="Art", album="Alb", genre="G", bpm=120, duration=100)
    session.add(s1)
    session.add(t1)
    session.commit()
    
    # Link track
    st = SetlistTrack(setlist_id=s1.id, track_id=t1.id, position=1)
    session.add(st)
    session.commit()
    
    response = client.get(f"/api/setlists/{s1.id}/export/m3u8")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/x-mpegurl"
    assert "#EXTM3U" in response.text
    assert "/music/song.mp3" in response.text

def test_recommend_next_track(client: TestClient, session: Session):
    # データ準備
    t1 = Track(filepath="/r1.mp3", title="R1", artist="A", album="B", genre="Techno", bpm=120, duration=100, key="1A", energy=0.8)
    t2 = Track(filepath="/r2.mp3", title="R2", artist="A", album="B", genre="Techno", bpm=122, duration=100, key="1A", energy=0.8)
    session.add(t1)
    session.add(t2)
    session.commit()

    # Embeddingデータを入れる
    from models import TrackEmbedding
    import json

    # ダミーの200次元ベクトル
    vec = [0.1] * 200
    te1 = TrackEmbedding(track_id=t1.id, embedding_json=json.dumps(vec))
    te2 = TrackEmbedding(track_id=t2.id, embedding_json=json.dumps(vec))
    session.add(te1)
    session.add(te2)
    session.commit()

    response = client.get("/api/recommendations/next", params={"track_id": t1.id})
    assert response.status_code == 200
    data = response.json()
    # 自分自身は除外されるはずなので、t2が返る
    assert len(data) > 0
    assert data[0]["title"] == "R2"

def test_generate_auto_setlist(client: TestClient, session: Session):
    t1 = Track(filepath="/a1.mp3", title="A1", artist="A", album="B", genre="House", bpm=120, duration=100, key="5A", energy=0.8)
    t2 = Track(filepath="/a2.mp3", title="A2", artist="A", album="B", genre="House", bpm=122, duration=100, key="5A", energy=0.8)
    t3 = Track(filepath="/a3.mp3", title="A3", artist="A", album="B", genre="House", bpm=124, duration=100, key="5A", energy=0.8)
    session.add(t1)
    session.add(t2)
    session.add(t3)
    session.commit()

    response = client.post("/api/recommendations/auto", json={"limit": 3})
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 3
