import os
import unicodedata
from typing import List, Dict, Any
from sqlmodel import Session, select
from models import Track, TrackEmbedding
import infra.database.connection as db_connection
from utils.filesystem import resolve_path
from utils.metadata import check_metadata_changed, has_valid_metadata
from domain.constants import SUPPORTED_EXTENSIONS

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
    
    # 読み取り専用セッション。DuckDBの並列読み取りを阻害しないよう短く閉じる。
    with Session(db_connection.engine) as session:
        # パスをNFCで正規化してマップを作成
        existing_tracks_query = session.exec(select(Track)).all()
        track_map = {normalize_path(t.filepath): t for t in existing_tracks_query}
        
        # Embeddingの存在確認
        existing_embeddings = session.exec(select(TrackEmbedding)).all()
        embedding_map = {e.track_id: True for e in existing_embeddings}
    
    files_to_process = []
    skipped_count = 0
    
    for fp in all_files:
        norm_fp = normalize_path(fp)
        should_skip = False
        
        if not force_update:
            existing_track = track_map.get(norm_fp)
            if existing_track:
                # 1. すでにBPM解析済みか
                is_analyzed = existing_track.bpm and existing_track.bpm > 0
                # 2. Embedding（ベクトルデータ）があるか
                has_embedding = existing_track.id in embedding_map
                # 3. メタデータ（タイトル/アーティスト）が正常か
                has_valid_meta = has_valid_metadata(existing_track)
                
                if is_analyzed and has_embedding and has_valid_meta:
                    # 4. ファイルタグ自体に変更がないか
                    # ここで差分がなければ真にスキップ対象
                    if not check_metadata_changed(fp, existing_track):
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
            if track.id not in embedding_map or not has_valid_metadata(track):
                return 0 # 高優先
            return 1 # メタデータ更新のみ等
        return 1 # 完全な新規ファイル

    files_to_process.sort(key=get_priority)
    
    return files_to_process, skipped_count