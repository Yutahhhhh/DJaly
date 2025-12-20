from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from api.schemas.common import IngestRequest
from app.services.ingestion_app_service import ingestion_app_service as ingestion_manager

router = APIRouter()

@router.post("/api/ingest")
async def ingest_files(req: IngestRequest):
    """
    Start ingestion background task.
    Returns immediately. Client should monitor progress via WebSocket.
    """
    if ingestion_manager.is_running:
        return {"status": "error", "message": "Ingestion already running"}
    
    # バックグラウンドタスク開始
    success = await ingestion_manager.start_ingestion(req.targets, req.force_update)
    
    if success:
        return {"status": "success", "message": "Ingestion started"}
    else:
        raise HTTPException(status_code=400, detail="Failed to start ingestion")

@router.post("/api/ingest/cancel")
async def cancel_ingest():
    """
    Cancel running ingestion task.
    """
    await ingestion_manager.cancel_ingestion()
    return {"status": "success", "message": "Ingestion cancelled"}

@router.websocket("/ws/ingest")
async def websocket_ingest(websocket: WebSocket):
    """
    WebSocket Endpoint for monitoring ingestion progress.
    Just connects to the manager and listens for broadcasts.
    """
    await ingestion_manager.connect(websocket)
    
    try:
        while True:
            # クライアントからのメッセージは現状不要だが、切断検知のために待機
            # 必要であれば "cancel" などのコマンドを受け付けることも可能
            await websocket.receive_text()
    except WebSocketDisconnect:
        ingestion_manager.disconnect(websocket)
    except Exception as e:
        print(f"WS Error: {e}")
        ingestion_manager.disconnect(websocket)