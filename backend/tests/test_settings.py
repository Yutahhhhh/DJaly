import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session
from models import Track, Setting

def test_get_settings(client: TestClient, session: Session):
    s = Setting(key="k", value="v")
    session.add(s)
    session.commit()
    
    response = client.get("/api/settings")
    assert response.status_code == 200
    data = response.json()
    assert data["k"] == "v"

def test_update_setting(client: TestClient, session: Session):
    response = client.post("/api/settings", json={"key": "new_k", "value": "new_v"})
    assert response.status_code == 200
    assert response.json()["key"] == "new_k"
    
    s = session.get(Setting, "new_k")
    assert s.value == "new_v"

def test_export_csv(client: TestClient, session: Session):
    t1 = Track(filepath="/c1.mp3", title="C1", artist="A", album="B", genre="G", bpm=120, duration=100)
    session.add(t1)
    session.commit()
    
    response = client.get("/api/settings/export/csv")
    assert response.status_code == 200
    assert "text/csv" in response.headers["content-type"]
    assert "C1" in response.text

def test_import_csv_analyze(client: TestClient, session: Session):
    csv_content = "filepath,title,artist,album,genre,bpm,duration\n/new.mp3,New,Art,Alb,G,120,100"
    files = {"file": ("import.csv", csv_content, "text/csv")}
    
    response = client.post("/api/settings/import/analyze", files=files)
    assert response.status_code == 200
    data = response.json()
    assert len(data["new_tracks"]) == 1
    assert data["new_tracks"][0]["title"] == "New"

def test_import_csv_execute(client: TestClient, session: Session):
    # analyzeの結果を使ってexecuteするわけではなく、executeは再度リクエストを送る形式か、
    # あるいはanalyzeの結果IDを送る形式か。
    # settings.pyを見ると、ImportExecuteRequestを受け取っている。
    # ImportExecuteRequestの中身は new_tracks などのリスト。
    
    req_data = {
        "new_tracks": [
            {"filepath": "/exec.mp3", "title": "Exec", "artist": "A", "album": "B", "genre": "G", "bpm": 120, "duration": 100}
        ],
        "path_updates": [],
        "metadata_updates": []
    }
    
    response = client.post("/api/settings/import/execute", json=req_data)
    assert response.status_code == 200
    data = response.json()
    assert data["imported"] == 1
    
    t = session.exec(select(Track).where(Track.filepath == "/exec.mp3")).first()
    assert t is not None
    
from sqlmodel import select

def test_metadata_export(client: TestClient, session: Session):
    t1 = Track(filepath="/m1.mp3", title="M1", artist="A", album="B", genre="G", bpm=120, duration=100)
    session.add(t1)
    session.commit()
    
    response = client.get("/api/settings/metadata/export")
    assert response.status_code == 200
    assert "M1" in response.text

def test_metadata_import_analyze(client: TestClient, session: Session):
    t1 = Track(filepath="/m2.mp3", title="Old", artist="A", album="B", genre="G", bpm=120, duration=100)
    session.add(t1)
    session.commit()
    
    # filepathを含める
    csv_content = f"filepath,title,artist,genre\n/m2.mp3,NewTitle,A,NewG"
    files = {"file": ("meta.csv", csv_content, "text/csv")}
    
    response = client.post("/api/settings/metadata/import/analyze", files=files)
    assert response.status_code == 200
    data = response.json()
    assert len(data["updates"]) == 1
    # updatesの中身は { "current": ..., "new": ... }
    assert data["updates"][0]["new"]["title"] == "NewTitle"

def test_metadata_import_execute(client: TestClient, session: Session):
    t1 = Track(filepath="/m3.mp3", title="Old", artist="A", album="B", genre="G", bpm=120, duration=100)
    session.add(t1)
    session.commit()
    
    req_data = {
        "updates": [
            {
                "filepath": "/m3.mp3", 
                "data": {
                    "filepath": "/m3.mp3",
                    "title": "Updated",
                    "artist": "A",
                    "album": "B",
                    "genre": "G"
                }
            }
        ]
    }
    
    response = client.post("/api/settings/metadata/import/execute", json=req_data)
    assert response.status_code == 200
    
    session.refresh(t1)
    assert t1.title == "Updated"
