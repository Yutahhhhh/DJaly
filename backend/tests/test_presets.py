from fastapi.testclient import TestClient
from sqlmodel import Session
from models import Preset, Prompt

def test_create_preset(client: TestClient, session: Session):
    # Promptが必要
    prompt = Prompt(name="P1", content="C1", is_default=False, display_order=1)
    session.add(prompt)
    session.commit()
    
    response = client.post("/api/presets", json={
        "name": "New Preset",
        "description": "Desc",
        "preset_type": "search",
        "filters": {"bpm": 120},
        "prompt_id": prompt.id
    })
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "New Preset"
    assert data["id"] is not None

def test_get_presets(client: TestClient, session: Session):
    # 初期データ投入 (conftestのmigrationで入っている可能性もあるが、明示的に追加)
    prompt = Prompt(name="P2", content="C2", is_default=False, display_order=1)
    session.add(prompt)
    session.commit()
    
    p1 = Preset(name="Preset 1", description="D1", preset_type="search", filters_json="{}", prompt_id=prompt.id)
    session.add(p1)
    session.commit()
    
    response = client.get("/api/presets")
    assert response.status_code == 200
    data = response.json()
    names = [p["name"] for p in data]
    assert "Preset 1" in names

def test_update_preset(client: TestClient, session: Session):
    prompt = Prompt(name="P3", content="C3", is_default=False, display_order=1)
    session.add(prompt)
    session.commit()
    
    p1 = Preset(name="Old Name", description="D", preset_type="search", filters_json="{}", prompt_id=prompt.id)
    session.add(p1)
    session.commit()
    
    response = client.put(f"/api/presets/{p1.id}", json={
        "name": "Updated Name",
        "description": "Updated Desc",
        "preset_type": "search",
        "filters": {},
        "prompt_id": prompt.id
    })
    assert response.status_code == 200
    assert response.json()["name"] == "Updated Name"

def test_delete_preset(client: TestClient, session: Session):
    prompt = Prompt(name="P4", content="C4", is_default=False, display_order=1)
    session.add(prompt)
    session.commit()
    
    p1 = Preset(name="To Delete", description="D", preset_type="search", filters_json="{}", prompt_id=prompt.id)
    session.add(p1)
    session.commit()
    
    response = client.delete(f"/api/presets/{p1.id}")
    assert response.status_code == 200
    
    assert session.get(Preset, p1.id) is None
