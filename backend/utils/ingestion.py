import os
from typing import List, Dict, Any
from sqlmodel import Session, select
from models import Track, TrackEmbedding
from db import engine
from utils.filesystem import resolve_path
from utils.metadata import check_metadata_changed
from constants import SUPPORTED_EXTENSIONS

def _collect_files_from_directory(directory: str) -> List[str]:
    files_list = []
    for root, _, files in os.walk(directory):
        for file in files:
            if file.lower().endswith(SUPPORTED_EXTENSIONS):
                files_list.append(os.path.join(root, file))
    return files_list

def expand_targets(targets: List[str]) -> List[str]:
    print(f"DEBUG: expand_targets called with {targets}")
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
    print(f"DEBUG: expand_targets returning {len(all_files)} files")
    return all_files

def has_valid_metadata(track: Track) -> bool:
    """
    トラックのメタデータが完全かどうかを判定する。
    ArtistやTitleが Unknown の場合は False を返す（再解析対象）。
    """
    if not track:
        return False
    
    # Check Artist
    if not track.artist or track.artist.lower() == "unknown":
        return False
        
    # Check Title (Unknown or matches filename exactly roughly)
    if not track.title or track.title.lower() == "unknown":
        return False
        
    return True

def filter_and_prioritize_files(targets: List[str], force_update: bool) -> tuple[List[str], int]:
    """
    ターゲットファイルリストを展開し、DBの状態に基づいてフィルタリングと優先順位付けを行う。
    
    Returns:
        (files_to_process, skipped_count)
    """
    all_files = expand_targets(targets)
    
    # --- Pre-fetch existing tracks for skip logic ---
    print("DEBUG: Pre-fetching existing tracks...")
    track_map = {}
    embedding_map = {}
    with Session(engine) as session:
        existing_tracks_query = session.exec(select(Track)).all()
        track_map = {t.filepath: t for t in existing_tracks_query}
        
        existing_embeddings = session.exec(select(TrackEmbedding)).all()
        embedding_map = {e.track_id: True for e in existing_embeddings}
    
    # Filter files to process
    files_to_process = []
    skipped_count = 0
    
    for fp in all_files:
        should_skip = False
        if not force_update:
            existing_track = track_map.get(fp)
            if existing_track:
                has_embedding = existing_track.id in embedding_map
                is_analyzed = existing_track.bpm and existing_track.bpm > 0
                has_valid_meta = has_valid_metadata(existing_track)
                
                # Only skip if EVERYTHING is good
                if is_analyzed and has_embedding and has_valid_meta:
                    # さらに念のため、メタデータの変更チェック（ここがボトルネックになる可能性はあるが正確性優先）
                    # ただし、has_valid_metaがTrueのものだけチェックすればよい
                    if not check_metadata_changed(fp, existing_track):
                        should_skip = True
        
        if should_skip:
            skipped_count += 1
        else:
            files_to_process.append(fp)
    
    # Sort Priority:
    # 0: Missing Embedding or Invalid Metadata (Needs work)
    # 1: New files
    def get_priority(filepath):
        track = track_map.get(filepath)
        if track:
            # If valid but missing embedding -> High Priority
            if track.id not in embedding_map:
                return 0
            # If invalid metadata -> High Priority
            if not has_valid_metadata(track):
                return 0
            return 1
        else:
            return 1 # New file

    files_to_process.sort(key=get_priority)
    
    return files_to_process, skipped_count
