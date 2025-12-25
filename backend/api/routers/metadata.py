from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Body, Depends, HTTPException
from pydantic import BaseModel
from typing import List, Optional
from sqlmodel import Session
from infra.database.connection import get_session
from models import Track, Lyrics
from utils.external_metadata import fetch_lrclib_lyrics
from datetime import datetime
from app.services.metadata_app_service import metadata_app_service

router = APIRouter()

class MetadataUpdateRequest(BaseModel):
    type: str # "release_date" | "lyrics"
    overwrite: bool = False
    track_ids: Optional[List[int]] = None

@router.post("/api/metadata/fetch-lyrics-single")
async def fetch_lyrics_single(
    track_id: int = Body(..., embed=True),
    session: Session = Depends(get_session)
):
    track = session.get(Track, track_id)
    if not track:
        raise HTTPException(status_code=404, detail="Track not found")

    data = await fetch_lrclib_lyrics(track.artist, track.title, track.album, track.duration)
    
    if not data:
        raise HTTPException(status_code=404, detail="Lyrics not found")

    content = data.get("syncedLyrics") or data.get("plainLyrics")
    if not content:
        raise HTTPException(status_code=404, detail="Lyrics content empty")

    lyrics = session.get(Lyrics, track_id)
    if not lyrics:
        lyrics = Lyrics(track_id=track_id)
        session.add(lyrics)
    
    lyrics.content = content
    lyrics.source = "lrclib"
    lyrics.updated_at = datetime.now()
    session.add(lyrics)
    session.commit()
    session.refresh(lyrics)

    return {"lyrics": content}

@router.post("/api/metadata/update")
async def start_update(req: MetadataUpdateRequest):
    success = await metadata_app_service.start_update(req.type, req.overwrite, req.track_ids)
    if success:
        return {"status": "success", "message": "Update started"}
    return {"status": "error", "message": "Update already running"}

@router.post("/api/metadata/cancel")
async def cancel_update():
    await metadata_app_service.cancel_update()
    return {"status": "success", "message": "Update cancelled"}

@router.websocket("/ws/metadata")
async def websocket_metadata(websocket: WebSocket):
    try:
        await metadata_app_service.connect(websocket)
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        metadata_app_service.disconnect(websocket)
    except Exception as e:
        # ClientDisconnected などもここでキャッチして静かに切断処理を行う
        # print(f"WS Error: {e}") 
        metadata_app_service.disconnect(websocket)
