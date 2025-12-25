from fastapi import APIRouter, HTTPException, Depends, Body
from fastapi.responses import FileResponse
from sqlmodel import Session
from infra.database.connection import get_session
from models import Track
from api.schemas.common import ListPathRequest, MetadataUpdate
from utils.filesystem import resolve_path
from app.services.filesystem_app_service import FilesystemAppService

router = APIRouter()

@router.get("/api/stream")
def stream_track(path: str):
    """オーディオファイルをストリーム再生用に提供する"""
    resolved_path = resolve_path(path)
    if not resolved_path:
        raise HTTPException(status_code=404, detail="File not found")
    
    return FileResponse(resolved_path)

@router.get("/api/metadata")
def get_track_metadata(track_id: int, session: Session = Depends(get_session)):
    """拡張メタデータを取得する。DBの解析データと物理ファイルのタグ情報を統合して返す"""
    service = FilesystemAppService(session)
    metadata = service.get_track_metadata(track_id)
    if not metadata:
        raise HTTPException(status_code=404, detail="Track not found or file missing")
    return metadata

@router.post("/api/fs/list")
def list_directory(req: ListPathRequest, session: Session = Depends(get_session)):
    """指定されたパス直下のファイル/フォルダ一覧を返す。解析済みステータスとフィルタリングを含む"""
    service = FilesystemAppService(session)
    result = service.list_directory(req.path)
    
    if result is None:
        raise HTTPException(status_code=404, detail="Path not found")

    if not req.hide_analyzed:
        return result

    return [item for item in result if not (not item['is_dir'] and item.get('is_analyzed'))]

@router.patch("/api/metadata/update")
def update_metadata_content(
    update: MetadataUpdate,
    session: Session = Depends(get_session)
):
    """物理ファイルのタグ情報（歌詞・アートワーク）を更新する"""
    service = FilesystemAppService(session)
    try:
        service.update_metadata_content(update.track_id, lyrics=update.lyrics, artwork_data=update.artwork_data)
    except ValueError:
        raise HTTPException(status_code=404, detail="Track not found")
    except RuntimeError:
        raise HTTPException(status_code=500, detail="Failed to write metadata to file")
    
    return {"status": "success"}

@router.post("/api/metadata/fetch-artwork-info")
def fetch_artwork_info(
    track_id: int = Body(..., embed=True),
    session: Session = Depends(get_session)
):
    """iTunes APIを使用してアートワーク画像を検索・取得し、Base64で返す"""
    service = FilesystemAppService(session)
    try:
        info = service.fetch_artwork_info(track_id)
        return {"info": info}
    except ValueError:
        raise HTTPException(status_code=404, detail="Track not found")
