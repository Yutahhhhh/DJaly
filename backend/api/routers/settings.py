from fastapi import APIRouter, Depends, UploadFile, File, HTTPException
from fastapi.responses import Response
from sqlmodel import Session
from typing import Dict, Any

from infra.database.connection import get_session
from api.schemas.common import SettingUpdate
from api.schemas.settings import (
    ImportAnalysisResult, ImportExecuteRequest,
    MetadataImportAnalysisResult, MetadataImportExecuteRequest,
    PresetImportAnalysisResult, PresetImportExecuteRequest
)
from app.services.setting_app_service import SettingAppService
from app.services.csv_app_service import CsvAppService

router = APIRouter()

@router.get("/api/settings")
def get_settings(session: Session = Depends(get_session)):
    service = SettingAppService(session)
    return service.get_settings()

@router.post("/api/settings")
def update_setting(setting: SettingUpdate, session: Session = Depends(get_session)):
    service = SettingAppService(session)
    return service.update_setting(setting)

# --- CSV Export ---
@router.get("/api/settings/export/csv")
def export_csv(session: Session = Depends(get_session)):
    """DB内の楽曲データをCSVとしてダウンロード"""
    service = CsvAppService(session)
    csv_content = service.export_tracks_to_csv()
    return Response(
        content=csv_content,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=djaly_library.csv"}
    )

# --- CSV Import (Analyze) ---
@router.post("/api/settings/import/analyze", response_model=ImportAnalysisResult)
async def analyze_import(file: UploadFile = File(...), session: Session = Depends(get_session)):
    """CSVをアップロードして解析（ドライラン）。差分情報を返す。"""
    content = await file.read()
    try:
        csv_str = content.decode("utf-8")
    except UnicodeDecodeError:
        csv_str = content.decode("shift-jis", errors="ignore")
    
    service = CsvAppService(session)
    result = service.analyze_csv_import(csv_str)
    
    # クライアントに返すために合計件数を計算
    result.total_rows = len(result.new_tracks) + len(result.duplicates) + len(result.path_updates)
    return result

# --- CSV Import (Execute) ---
@router.post("/api/settings/import/execute")
def execute_import_endpoint(req: ImportExecuteRequest, session: Session = Depends(get_session)):
    """ユーザー確認後にインポートを実行"""
    service = CsvAppService(session)
    import_count, update_count = service.execute_import(req)
    
    return {
        "status": "success", 
        "imported": import_count, 
        "updated": update_count,
        "message": f"Successfully imported {import_count} new tracks and updated {update_count} paths."
    }

# --- Metadata CSV Operations ---

@router.get("/api/settings/metadata/export")
def export_metadata(session: Session = Depends(get_session)):
    """メタデータ編集用の軽量CSVをエクスポート"""
    service = CsvAppService(session)
    csv_content = service.export_metadata_csv()
    return Response(
        content=csv_content,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=djaly_metadata.csv"}
    )

@router.post("/api/settings/metadata/import/analyze", response_model=MetadataImportAnalysisResult)
async def analyze_metadata(file: UploadFile = File(...), session: Session = Depends(get_session)):
    """メタデータCSVを解析"""
    content = await file.read()
    try:
        csv_str = content.decode("utf-8")
    except UnicodeDecodeError:
        csv_str = content.decode("shift-jis", errors="ignore")
        
    service = CsvAppService(session)
    return service.analyze_metadata_import(csv_str)

@router.post("/api/settings/metadata/import/execute")
def execute_metadata(req: MetadataImportExecuteRequest, session: Session = Depends(get_session)):
    """メタデータ更新を実行"""
    service = CsvAppService(session)
    count = service.execute_metadata_import(req)
    return {
        "status": "success",
        "updated": count,
        "message": f"Successfully updated {count} tracks."
    }

# --- Preset CSV Operations ---

@router.get("/api/settings/presets/export")
def export_presets(session: Session = Depends(get_session)):
    """プリセットをCSVとしてエクスポート"""
    service = CsvAppService(session)
    csv_content = service.export_presets_csv()
    return Response(
        content=csv_content,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=djaly_presets.csv"}
    )

@router.post("/api/settings/presets/import/analyze", response_model=PresetImportAnalysisResult)
async def analyze_presets(file: UploadFile = File(...), session: Session = Depends(get_session)):
    """プリセットCSVを解析"""
    content = await file.read()
    try:
        csv_str = content.decode("utf-8")
    except UnicodeDecodeError:
        csv_str = content.decode("shift-jis", errors="ignore")
        
    service = CsvAppService(session)
    return service.analyze_presets_import(csv_str)

@router.post("/api/settings/presets/import/execute")
def execute_presets(req: PresetImportExecuteRequest, session: Session = Depends(get_session)):
    """プリセットインポートを実行"""
    service = CsvAppService(session)
    count = service.execute_presets_import(req)
    return {
        "status": "success",
        "imported": count,
        "message": f"Successfully processed {count} presets."
    }
