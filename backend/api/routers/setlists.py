from fastapi import APIRouter, Depends, HTTPException, Body, Query
from fastapi.responses import Response
from sqlmodel import Session
from typing import List, Optional, Dict, Any
import re
import urllib.parse

from db import get_session
from models import Setlist
from services.setlists import SetlistService

router = APIRouter()
setlist_service = SetlistService()

@router.get("/api/setlists")
def get_setlists(session: Session = Depends(get_session)):
    return setlist_service.get_setlists(session)

@router.post("/api/setlists")
def create_setlist(name: str = Body(embed=True), session: Session = Depends(get_session)):
    return setlist_service.create_setlist(session, name)

@router.put("/api/setlists/{setlist_id}")
def update_setlist(setlist_id: int, setlist_data: Dict[str, Any], session: Session = Depends(get_session)):
    setlist = setlist_service.update_setlist(session, setlist_id, setlist_data)
    if not setlist:
        raise HTTPException(status_code=404, detail="Setlist not found")
    return setlist

@router.delete("/api/setlists/{setlist_id}")
def delete_setlist(setlist_id: int, session: Session = Depends(get_session)):
    success = setlist_service.delete_setlist(session, setlist_id)
    if not success:
        raise HTTPException(status_code=404, detail="Setlist not found")
    return {"ok": True}

@router.get("/api/setlists/{setlist_id}/tracks")
def get_setlist_tracks(setlist_id: int, session: Session = Depends(get_session)):
    return setlist_service.get_setlist_tracks(session, setlist_id)

@router.post("/api/setlists/{setlist_id}/tracks")
def update_setlist_tracks(
    setlist_id: int, 
    track_ids: List[int] = Body(...), 
    session: Session = Depends(get_session)
):
    success = setlist_service.update_setlist_tracks(session, setlist_id, track_ids)
    if not success:
        raise HTTPException(status_code=404, detail="Setlist not found")
    return {"status": "success"}

@router.get("/api/setlists/{setlist_id}/export/m3u8")
def export_setlist_m3u8(setlist_id: int, session: Session = Depends(get_session)):
    """
    Rekordbox等のためのM3U8プレイリストをダウンロードする
    """
    try:
        content = setlist_service.export_as_m3u8(session, setlist_id)
        
        # セットリスト名を取得してファイル名にする
        setlist = session.get(Setlist, setlist_id)
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
    try:
        return setlist_service.recommend_next_track(session, track_id, limit, preset_id, genres)
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
    try:
        return setlist_service.generate_auto_setlist(session, preset_id, limit, seed_track_ids, genres)
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
    try:
        return setlist_service.generate_path_setlist(session, start_track_id, end_track_id, length, genres)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))