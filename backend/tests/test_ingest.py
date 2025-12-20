import pytest
from fastapi.testclient import TestClient
from services.ingestion_manager import ingestion_manager

@pytest.mark.asyncio
async def test_ingest_start(client: TestClient, mocker):
    # start_ingestion をモック (AsyncMock)
    mock_start = mocker.patch.object(ingestion_manager, "start_ingestion", new_callable=mocker.AsyncMock)
    mock_start.return_value = True
    
    # is_running プロパティをモック
    mocker.patch.object(ingestion_manager, "is_running", False)
    
    response = client.post("/api/ingest", json={"targets": ["/music"], "force_update": False})
    assert response.status_code == 200
    assert response.json()["status"] == "success"
    
    mock_start.assert_called_once_with(["/music"], False)

@pytest.mark.asyncio
async def test_ingest_already_running(client: TestClient, mocker):
    mocker.patch.object(ingestion_manager, "is_running", True)
    
    response = client.post("/api/ingest", json={"targets": ["/music"]})
    assert response.status_code == 200
    assert response.json()["status"] == "error"

@pytest.mark.asyncio
async def test_ingest_cancel(client: TestClient, mocker):
    mock_cancel = mocker.patch.object(ingestion_manager, "cancel_ingestion", new_callable=mocker.AsyncMock)
    
    response = client.post("/api/ingest/cancel")
    assert response.status_code == 200
    
    mock_cancel.assert_called_once()

def test_websocket_ingest(client: TestClient):
    # WebSocketのテスト
    # 接続して即切断でもOK
    with client.websocket_connect("/ws/ingest") as websocket:
        pass
