from fastapi import APIRouter, Depends, HTTPException, Body, Query
from fastapi.responses import Response
from sqlmodel import Session
from typing import List, Optional, Dict, Any
import re
import urllib.parse

from infra.database.connection import get_session
from domain.models.setlist import Setlist
from app.services.setlist_app_service import SetlistAppService

router = APIRouter()

@router.get("/api/setlists")
def get_setlists(session: Session = Depends(get_session)):
    service = SetlistAppService(session)
    return service.get_setlists()

@router.post("/api/setlists")
def create_setlist(name: str = Body(embed=True), session: Session = Depends(get_session)):
    service = SetlistAppService(session)
    return service.create_setlist(name)

@router.put("/api/setlists/{setlist_id}")
def update_setlist(setlist_id: int, setlist_data: Dict[str, Any], session: Session = Depends(get_session)):
    service = SetlistAppService(session)
    setlist = service.update_setlist(setlist_id, setlist_data)
    if not setlist:
        raise HTTPException(status_code=404, detail="Setlist not found")
    return setlist

@router.delete("/api/setlists/{setlist_id}")
def delete_setlist(setlist_id: int, session: Session = Depends(get_session)):
    service = SetlistAppService(session)
    success = service.delete_setlist(setlist_id)
    if not success:
        raise HTTPException(status_code=404, detail="Setlist not found")
    return {"ok": True}

@router.get("/api/setlists/{setlist_id}/tracks")
def get_setlist_tracks(setlist_id: int, session: Session = Depends(get_session)):
    service = SetlistAppService(session)
    return service.get_setlist_tracks(setlist_id)

@router.post("/api/setlists/{setlist_id}/tracks")
def update_setlist_tracks(
    setlist_id: int, 
    track_data: List[Any] = Body(...),
    session: Session = Depends(get_session)
):
    service = SetlistAppService(session)
    success = service.update_setlist_tracks(setlist_id, track_data)
    if not success:
        raise HTTPException(status_code=404, detail="Setlist not found")
    return {"status": "success"}

@router.get("/api/setlists/{setlist_id}/export/m3u8")
def export_setlist_m3u8(setlist_id: int, session: Session = Depends(get_session)):
    """
    Rekordbox等のためのM3U8プレイリストをダウンロードする
    """
    service = SetlistAppService(session)
    try:
        content = service.export_as_m3u8(setlist_id)
        
        # セットリスト名を取得してファイル名にする
        setlist = service.repository.get_by_id(setlist_id)
        filename = f"{setlist.name}.m3u8" if setlist else "playlist.m3u8"
        # ファイル名に使えない文字を置換
        filename = re.sub(r'[\\/*?:"<>|]', "", filename)

        return Response(
            content=content,
            media_type="application/x-mpegurl",
            headers={"Content-Disposition": f"attachment; filename*=UTF-8''{urllib.parse.quote(filename)}"}
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

@router.get("/api/recommendations/next")
def recommend_next_track(
    track_id: int, 
    limit: int = 20, 
    preset_id: Optional[int] = Query(None),
    genres: Optional[List[str]] = Query(None),
    session: Session = Depends(get_session)
):
    """
    指定された曲に続く、相性の良い曲を提案する。
    Hybrid Scoring (Vector + BPM + Key) を使用。
    """
    service = SetlistAppService(session)
    try:
        return service.recommend_next_track(track_id, limit, preset_id, genres)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

@router.post("/api/recommendations/auto")
def generate_auto_setlist(
    preset_id: int = Body(...),
    limit: int = Body(10),
    seed_track_ids: Optional[List[int]] = Body(None),
    genres: Optional[List[str]] = Body(None),
    session: Session = Depends(get_session)
):
    """
    プリセット(LLM解析)とChain Builderアルゴリズムに基づいてセットリストを自動生成する。
    """
    service = SetlistAppService(session)
    try:
        return service.generate_auto_setlist(preset_id, limit, seed_track_ids, genres)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

@router.post("/api/recommendations/path")
def generate_path_setlist(
    start_track_id: int = Body(...),
    end_track_id: int = Body(...),
    length: int = Body(10),
    genres: Optional[List[str]] = Body(None),
    session: Session = Depends(get_session)
):
    """
    2曲間を繋ぐセットリストを生成する (Pathfinding)
    """
    service = SetlistAppService(session)
    try:
        return service.generate_path_setlist(start_track_id, end_track_id, length, genres)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
@router.patch("/api/setlist-tracks/{setlist_track_id}/wordplay")
def update_setlist_track_wordplay(
    setlist_track_id: int,
    wordplay_json: str = Body(..., embed=True),
    session: Session = Depends(get_session)
):
    from domain.models.setlist import SetlistTrack
    
    track = session.get(SetlistTrack, setlist_track_id)
    if not track:
        raise HTTPException(status_code=404, detail="Setlist track not found")
        
    track.wordplay_json = wordplay_json
    session.add(track)
    session.commit()
    session.refresh(track)
    return track
