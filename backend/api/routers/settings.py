from fastapi import APIRouter, Depends, UploadFile, File, HTTPException
from fastapi.responses import Response
from sqlmodel import Session
from typing import Dict, Any

from db import get_session
from schemas.common import SettingUpdate
from schemas.settings import (
    ImportAnalysisResult, ImportExecuteRequest,
    MetadataImportAnalysisResult, MetadataImportExecuteRequest,
    PresetImportAnalysisResult, PresetImportExecuteRequest
)
from services.csv_manager import (
    export_tracks_to_csv, analyze_csv_import, execute_import,
    export_metadata_csv, analyze_metadata_import, execute_metadata_import,
    export_presets_csv, analyze_presets_import, execute_presets_import
)
from services.settings import SettingsService

router = APIRouter()
settings_service = SettingsService()

@router.get("/api/settings")
def get_settings(session: Session = Depends(get_session)):
    return settings_service.get_settings(session)

@router.post("/api/settings")
def update_setting(setting: SettingUpdate, session: Session = Depends(get_session)):
    return settings_service.update_setting(session, setting)

# --- CSV Export ---
@router.get("/api/settings/export/csv")
def export_csv(session: Session = Depends(get_session)):
    """DB内の楽曲データをCSVとしてダウンロード"""
    csv_content = export_tracks_to_csv(session)
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
    
    # 【修正】session (Depends(get_session)) が既にロックを持っているので、ここではロック不要
    # analyze_csv_import は内部で session を使うだけなので安全
    result = analyze_csv_import(session, csv_str)
    
    # クライアントに返すために合計件数を計算
    result.total_rows = len(result.new_tracks) + len(result.duplicates) + len(result.path_updates)
    return result

# --- CSV Import (Execute) ---
@router.post("/api/settings/import/execute")
def execute_import_endpoint(req: ImportExecuteRequest, session: Session = Depends(get_session)):
    """ユーザー確認後にインポートを実行"""
    import_count, update_count = execute_import(session, req)
    
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
    csv_content = export_metadata_csv(session)
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
        
    return analyze_metadata_import(session, csv_str)

@router.post("/api/settings/metadata/import/execute")
def execute_metadata(req: MetadataImportExecuteRequest, session: Session = Depends(get_session)):
    """メタデータ更新を実行"""
    count = execute_metadata_import(session, req)
    return {
        "status": "success",
        "updated": count,
        "message": f"Successfully updated metadata for {count} tracks."
    }

# --- Preset CSV Operations ---

@router.get("/api/settings/presets/export")
def export_presets(session: Session = Depends(get_session)):
    """プリセットをCSVとしてエクスポート"""
    csv_content = export_presets_csv(session)
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
        
    return analyze_presets_import(session, csv_str)

@router.post("/api/settings/presets/import/execute")
def execute_presets(req: PresetImportExecuteRequest, session: Session = Depends(get_session)):
    """プリセットインポートを実行"""
    count = execute_presets_import(session, req)
    return {
        "status": "success",
        "updated": count,
        "message": f"Successfully imported/updated {count} presets."
    }
