from fastapi import APIRouter, Depends, Query, HTTPException, Body
from sqlmodel import Session
from typing import List, Optional
from infra.database.connection import get_session
from api.schemas.common import PresetCreate, PresetUpdate
from app.services.preset_app_service import PresetAppService

router = APIRouter()

@router.get("/api/presets")
def get_presets(
    type: Optional[str] = Query(None, description="Filter by preset type"),
    strict: bool = Query(False, description="If true, match type exactly (exclude 'all')"),
    session: Session = Depends(get_session)
):
    """
    プリセット一覧を取得する。
    strict=True の場合、指定された type と完全に一致するもののみを返す。
    strict=False (デフォルト) の場合、type='generation' でも 'all' (汎用) を含めて返す。
    """
    service = PresetAppService(session)
    return service.get_presets(type, strict)

@router.post("/api/presets")
def create_preset(preset: PresetCreate, session: Session = Depends(get_session)):
    service = PresetAppService(session)
    return service.create_preset(preset)

@router.put("/api/presets/{preset_id}")
def update_preset(preset_id: int, preset: PresetUpdate, session: Session = Depends(get_session)):
    service = PresetAppService(session)
    result = service.update_preset(preset_id, preset)
    if not result:
        raise HTTPException(status_code=404, detail="Preset not found")
    return result

@router.delete("/api/presets/{preset_id}")
def delete_preset(preset_id: int, session: Session = Depends(get_session)):
    service = PresetAppService(session)
    success = service.delete_preset(preset_id)
    if not success:
        raise HTTPException(status_code=404, detail="Preset not found")
    return {"ok": True}
