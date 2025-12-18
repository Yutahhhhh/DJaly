from fastapi import APIRouter, Depends, Query, HTTPException, Body
from sqlmodel import Session
from typing import List, Optional
from db import get_session
from schemas.common import PresetCreate, PresetUpdate
from services.presets import PresetService

router = APIRouter()
preset_service = PresetService()

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
    return preset_service.get_presets(session, type, strict)

@router.post("/api/presets")
def create_preset(preset: PresetCreate, session: Session = Depends(get_session)):
    return preset_service.create_preset(session, preset)

@router.put("/api/presets/{preset_id}")
def update_preset(preset_id: int, preset: PresetUpdate, session: Session = Depends(get_session)):
    result = preset_service.update_preset(session, preset_id, preset)
    if not result:
        raise HTTPException(status_code=404, detail="Preset not found")
    return result

@router.delete("/api/presets/{preset_id}")
def delete_preset(preset_id: int, session: Session = Depends(get_session)):
    success = preset_service.delete_preset(session, preset_id)
    if not success:
        raise HTTPException(status_code=404, detail="Preset not found")
    return {"ok": True}
