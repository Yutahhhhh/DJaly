from fastapi.testclient import TestClient
from sqlmodel import Session
from models import Prompt

def test_create_prompt(client: TestClient, session: Session):
    response = client.post("/api/prompts", json={
        "name": "New Prompt",
        "content": "Content",
        "is_default": False,
        "display_order": 10
    })
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "New Prompt"

def test_get_prompts(client: TestClient, session: Session):
    p1 = Prompt(name="P1", content="C1", is_default=False, display_order=1)
    session.add(p1)
    session.commit()
    
    response = client.get("/api/prompts")
    assert response.status_code == 200
    data = response.json()
    names = [p["name"] for p in data]
    assert "P1" in names

def test_update_prompt(client: TestClient, session: Session):
    p1 = Prompt(name="Old P", content="C", is_default=False, display_order=1)
    session.add(p1)
    session.commit()
    
    response = client.put(f"/api/prompts/{p1.id}", json={
        "name": "Updated P",
        "content": "Updated C",
        "is_default": True,
        "display_order": 5
    })
    assert response.status_code == 200
    assert response.json()["name"] == "Updated P"

def test_delete_prompt(client: TestClient, session: Session):
    p1 = Prompt(name="Del P", content="C", is_default=False, display_order=1)
    session.add(p1)
    session.commit()
    
    response = client.delete(f"/api/prompts/{p1.id}")
    assert response.status_code == 200
    assert session.get(Prompt, p1.id) is None
