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

@router.get("/api/setlists/{setlist_id}/duration")
def get_setlist_duration(setlist_id: int, session: Session = Depends(get_session)):
    service = SetlistAppService(session)
    if not service.repository.get_by_id(setlist_id):
        raise HTTPException(status_code=404, detail="Setlist not found")
    try:
        return service.set_duration(setlist_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

@router.post("/api/setlists/{setlist_id}/tracks")
def update_setlist_tracks(
    setlist_id: int, 
    track_data: List[Any] = Body(...),
    session: Session = Depends(get_session)
):
    service = SetlistAppService(session)
    try:
        success = service.update_setlist_tracks(setlist_id, track_data)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
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

@router.get("/api/setlists/{setlist_id}/export/validate")
def validate_setlist_export(setlist_id: int, session: Session = Depends(get_session)):
    """
    エクスポート前にセットリスト内の楽曲ファイルの存在を検証する。
    """
    service = SetlistAppService(session)
    try:
        return service.validate_export(setlist_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

@router.get("/api/recommendations/next")
def recommend_next_track(
    track_id: int,
    limit: int = 20,
    genres: Optional[List[str]] = Query(None),
    subgenres: Optional[List[str]] = Query(None),
    session: Session = Depends(get_session)
):
    """
    指定された曲に続く、相性の良い曲を提案する。
    Hybrid Scoring (Vector + BPM + Key) を使用。
    """
    service = SetlistAppService(session)
    try:
        return service.recommend_next_track(track_id, limit, None, genres, subgenres)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

@router.get("/api/recommendations/next/page")
def recommend_next_track_page(
    track_id: int,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    genres: Optional[List[str]] = Query(None),
    subgenres: Optional[List[str]] = Query(None),
    target_bpm: Optional[float] = None,
    target_energy: Optional[float] = None,
    target_danceability: Optional[float] = None,
    target_brightness: Optional[float] = None,
    target_noisiness: Optional[float] = None,
    year_min: Optional[int] = None,
    year_max: Optional[int] = None,
    session: Session = Depends(get_session),
):
    """Globally ranked recommendation page with an exact eligible total."""
    try:
        return SetlistAppService(session).recommend_next_track_page(
            track_id, limit=limit, offset=offset,
            target_params={
                "bpm": target_bpm, "energy": target_energy,
                "danceability": target_danceability, "brightness": target_brightness,
                "noisiness": target_noisiness, "year_min": year_min, "year_max": year_max,
            },
            genres=genres, subgenres=subgenres,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

@router.post("/api/recommendations/auto")
def generate_auto_setlist(
    limit: Optional[int] = Body(None),
    min_length: Optional[int] = Body(None),
    max_length: Optional[int] = Body(None),
    seed_track_ids: Optional[List[int]] = Body(None),
    genres: Optional[List[str]] = Body(None),
    subgenres: Optional[List[str]] = Body(None),
    session: Session = Depends(get_session)
):
    """
    Chain Builderアルゴリズムに基づいてセットリストを自動生成する。
    自然言語の解釈はMCPクライアント側で行う。
    曲数は limit / min_length〜max_length で指定可能（未指定時は設定のデフォルト曲数）。
    """
    service = SetlistAppService(session)
    try:
        return service.generate_auto_setlist(None, limit, min_length, max_length, seed_track_ids, genres, subgenres)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

@router.post("/api/recommendations/path")
def generate_path_setlist(
    start_track_id: int = Body(...),
    end_track_id: int = Body(...),
    length: int = Body(10),
    genres: Optional[List[str]] = Body(None),
    subgenres: Optional[List[str]] = Body(None),
    session: Session = Depends(get_session)
):
    """
    2曲間を繋ぐセットリストを生成する (Pathfinding)
    """
    service = SetlistAppService(session)
    try:
        return service.generate_path_setlist(start_track_id, end_track_id, length, genres, subgenres)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

@router.patch("/api/setlist-tracks/{setlist_track_id}/wordplay")
def update_setlist_track_wordplay(
    setlist_track_id: int,
    wordplay_json: Optional[str] = Body(None, embed=True),
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
