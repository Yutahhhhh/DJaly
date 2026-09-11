import os
import json
import math
import unicodedata
from types import SimpleNamespace
from typing import List, Dict, Any
from sqlmodel import Session, select
from models import Track, TrackEmbedding
import infra.database.connection as db_connection
from utils.filesystem import resolve_path
from utils.metadata import check_metadata_changed, has_valid_metadata
from domain.constants import SUPPORTED_EXTENSIONS
from domain.constants import EMBEDDING_DIM


def has_valid_embedding(embedding: Any) -> bool:
    """Reject missing, malformed, non-finite and placeholder embeddings."""
    value = getattr(embedding, "embedding_json", embedding)
    try:
        vector = json.loads(value) if isinstance(value, str) else list(value)
        return (
            len(vector) == EMBEDDING_DIM
            and all(
                isinstance(item, (int, float))
                and not isinstance(item, bool)
                and math.isfinite(item)
                for item in vector
            )
            and any(item != 0 for item in vector)
        )
    except (TypeError, ValueError, json.JSONDecodeError):
        return False


def has_completed_analysis(track: Any, embedding: Any) -> bool:
    """The single definition used by filtering, Explorer badges and imports."""
    return bool(
        track
        and isinstance(getattr(track, "bpm", None), (int, float))
        and not isinstance(track.bpm, bool)
        and track.bpm > 0
        and has_valid_embedding(embedding)
        and has_valid_metadata(track)
    )


def has_completed_analysis_result(result: Dict[str, Any], existing_embedding: Any = None) -> bool:
    """Validate a fresh full-analysis result before it is reported or saved."""
    bpm = result.get("bpm")
    duration = result.get("duration")
    embedding = result.get("embedding", existing_embedding)
    metadata = SimpleNamespace(title=result.get("title"), artist=result.get("artist"))
    return bool(
        isinstance(bpm, (int, float)) and not isinstance(bpm, bool) and math.isfinite(bpm) and bpm > 0
        and isinstance(duration, (int, float)) and not isinstance(duration, bool) and math.isfinite(duration) and duration > 0
        and has_valid_embedding(embedding)
        and has_valid_metadata(metadata)
    )

def normalize_path(path: str) -> str:
    """
    MacOS(NFD)とDB/Linux(NFC)のパスの差異を吸収するため、
    一貫してNFCに正規化して比較を行う。
    """
    return unicodedata.normalize('NFC', path)

def _collect_files_from_directory(directory: str) -> List[str]:
    files_list = []
    for root, _, files in os.walk(directory):
        for file in files:
            if file.lower().endswith(SUPPORTED_EXTENSIONS):
                files_list.append(os.path.join(root, file))
    return files_list

def expand_targets(targets: List[str]) -> List[str]:
    all_files = []
    for target in targets:
        resolved_target = resolve_path(target)
        if not resolved_target:
            continue
        if os.path.isfile(resolved_target):
            if resolved_target.lower().endswith(SUPPORTED_EXTENSIONS):
                all_files.append(resolved_target)
        elif os.path.isdir(resolved_target):
            files = _collect_files_from_directory(resolved_target)
            all_files.extend(files)
    return all_files

def filter_and_prioritize_files(targets: List[str], force_update: bool) -> tuple[List[str], int]:
    """
    ターゲットファイルリストを展開し、DBの状態に基づいてフィルタリングと優先順位付けを行う。
    """
    all_files = expand_targets(targets)
    
    track_map = {}
    embedding_map = {}
    lyrics_map = {}
    
    # 読み取り専用セッション。DuckDBの並列読み取りを阻害しないよう短く閉じる。
    with Session(db_connection.engine) as session:
        # パスをNFCで正規化してマップを作成
        existing_tracks_query = session.exec(select(Track)).all()
        track_map = {normalize_path(t.filepath): t for t in existing_tracks_query}
        
        # Embeddingの存在確認
        existing_embeddings = session.exec(select(TrackEmbedding)).all()
        embedding_map = {e.track_id: e for e in existing_embeddings}
        
        # Lyricsの存在確認
        from domain.models.lyrics import Lyrics
        existing_lyrics = session.exec(select(Lyrics)).all()
        lyrics_map = {ly.track_id: True for ly in existing_lyrics}
    
    files_to_process = []
    skipped_count = 0
    
    for fp in all_files:
        norm_fp = normalize_path(fp)
        should_skip = False
        
        if not force_update:
            existing_track = track_map.get(norm_fp)
            if existing_track:
                embedding = embedding_map.get(existing_track.id)
                # .lrcファイルが存在するか（内容の差分チェックは後段で行う）
                lrc_path = os.path.splitext(fp)[0] + ".lrc"
                has_lrc_file = os.path.exists(lrc_path)
                
                if has_completed_analysis(existing_track, embedding):
                    # .lrcファイルがある場合、内容が変更されている可能性があるため処理する
                    # （実際の差分チェックはingestion_domain_serviceで行われる）
                    if has_lrc_file:
                        should_skip = False
                    # ファイルタグ自体に変更がないか
                    elif not check_metadata_changed(fp, existing_track):
                        should_skip = True
        
        if should_skip:
            skipped_count += 1
        else:
            files_to_process.append(fp)
    
    # 優先順位付け: 解析が不完全なものを先に処理する
    def get_priority(filepath):
        norm_fp = normalize_path(filepath)
        track = track_map.get(norm_fp)
        if track:
            if not has_completed_analysis(track, embedding_map.get(track.id)):
                return 0 # 高優先
            return 1 # メタデータ更新のみ等
        return 1 # 完全な新規ファイル

    files_to_process.sort(key=get_priority)
    
    return files_to_process, skipped_count
