import os
from typing import List, Set, Dict, Any, Optional
from sqlmodel import Session, select
from constants import SUPPORTED_EXTENSIONS
from utils.filesystem import resolve_path
from utils.metadata import extract_full_metadata
from models import Track, TrackAnalysis

def _is_supported_file(filename: str) -> bool:
    """ファイル名がサポートされている拡張子かチェックする"""
    return filename.lower().endswith(SUPPORTED_EXTENSIONS)

def _has_visible_content(directory_path: str, hide_analyzed: bool, analyzed_paths: Set[str]) -> bool:
    try:
        for root, _, files in os.walk(directory_path):
            for file in files:
                if file.startswith('.'):
                    continue
                
                if _is_supported_file(file):
                    if not hide_analyzed:
                        return True
                    
                    full_path = os.path.join(root, file)
                    if full_path not in analyzed_paths:
                        return True
        return False
    except (PermissionError, OSError):
        return False

class FilesystemService:
    def get_track_metadata(self, session: Session, track_id: int) -> Dict[str, Any]:
        """
        拡張メタデータを取得する。
        DBに解析データ（波形ピーク、ビート、BPMなど）があればそれを優先して返す。
        なければTinyTagで簡易情報を返す。
        """
        track = session.get(Track, track_id)
        if not track:
            return None

        resolved_path = resolve_path(track.filepath)
        if not resolved_path:
            return None
        
        # 1. DB検索 (解析済みデータの取得)
        # Fetch heavy data from TrackAnalysis
        analysis = session.get(TrackAnalysis, track_id)
        if analysis:
            db_metadata = {
                "bpm": track.bpm,
                "key": track.key,
                "beat_positions": analysis.beat_positions,
                "waveform_peaks": analysis.waveform_peaks,
                "analyzed": True
            }
        else:
            db_metadata = {
                "bpm": track.bpm,
                "key": track.key,
                "beat_positions": [],
                "waveform_peaks": [],
                "analyzed": False
            }

        # 2. ファイルタグ情報の取得 (Artwork, Lyrics)
        tag_metadata = extract_full_metadata(resolved_path)

        # 3. マージして返す (DBの情報があればそちらを優先する項目も調整可能)
        return {
            **tag_metadata,
            **db_metadata
        }

    def list_directory(self, session: Session, path: str) -> List[Dict[str, Any]]:
        """指定されたパス直下のファイル/フォルダ一覧を返す"""
        search_path = resolve_path(path)
        if not search_path:
            return None
        
        try:
            items = []

            with os.scandir(search_path) as it:
                for entry in it:
                    if entry.name.startswith('.'):
                        continue
                    
                    if entry.is_dir():
                        # 高速化のため、ディレクトリの中身チェック（再帰スキャン）をスキップする
                        pass
                    
                    else:
                        if not _is_supported_file(entry.name):
                            continue

                    item = {
                        "name": entry.name,
                        "path": entry.path,
                        "is_dir": entry.is_dir(),
                        "is_analyzed": False
                    }
                    items.append(item)

            items.sort(key=lambda x: (not x['is_dir'], x['name'].lower()))
            
            # Check against DB for analyzed status
            file_paths = [item['path'] for item in items if not item['is_dir']]
            
            analyzed_files = set()
            if file_paths:
                statement = select(Track.filepath).where(Track.filepath.in_(file_paths))
                analyzed_files = set(session.exec(statement).all())

            # Filter or Mark items
            final_result = []
            for item in items:
                if not item['is_dir']:
                    item['is_analyzed'] = item['path'] in analyzed_files
                final_result.append(item)
                
            return final_result

        except Exception as e:
            import traceback
            traceback.print_exc()
            raise e

# Legacy function for backward compatibility if needed, but better to use class
def list_directory_service(path: str) -> List[Dict[str, Any]]:
    # This function is deprecated and should be replaced by FilesystemService.list_directory
    # However, it doesn't have session access, so it can't check analyzed status.
    # We keep the basic implementation for now or remove it if not used elsewhere.
    pass