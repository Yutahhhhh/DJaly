import os
import asyncio
import re
import json
from typing import List, Dict, Any, Optional
from concurrent.futures import Executor
from sqlmodel import Session, select, text
from sqlalchemy.exc import IntegrityError
from models import Track, TrackEmbedding
from tinytag import TinyTag
# ingestからのインポートは関数のみにする
from ingest import analyze_track_file
# 定数はconstantsから
from constants import SUPPORTED_EXTENSIONS
from utils.filesystem import resolve_path
from utils.metadata import extract_metadata_smart, check_metadata_changed
from db import engine, db_lock
from utils.llm import generate_text
from datetime import datetime

from services.ingestion_db import save_to_db
from utils.ingestion import expand_targets, has_valid_metadata

def _clean_llm_response(text: str) -> str:
    if not text: return ""
    lines = text.split('\n')
    candidate_line = ""
    for line in lines:
        clean_line = line.strip()
        if not clean_line: continue
        match = re.match(r'^(Genre|Output|Result|Classification):\s*(.+)', clean_line, re.IGNORECASE)
        if match:
            candidate_line = match.group(2)
            break
    if not candidate_line:
        for line in lines:
            clean_line = line.strip()
            lower_line = clean_line.lower()
            if any(phrase in lower_line for phrase in ["based on", "i would classify", "here are", "context:", "output format:"]):
                continue
            if len(clean_line) > 2:
                candidate_line = clean_line
                break
    if candidate_line:
        cleaned = re.sub(r"['\"\[\]\.]", "", candidate_line)
        return cleaned.strip()
    return ""

def _process_metadata_update(filepath: str, existing_data_cache: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    filename = os.path.basename(filepath)
    try:
        tag = TinyTag.get(filepath)
        meta = extract_metadata_smart(filepath, tag)
        
        print(f"DEBUG: Metadata extracted for {filename}: Artist='{meta.get('artist')}', Title='{meta.get('title')}'")

        # 既存のDB値が有効ならそれを優先（metadata_update_onlyはforce_update=Falseの時のみなので）
        if existing_data_cache.get("genre") and existing_data_cache["genre"].lower() != "unknown":
            new_genre = existing_data_cache["genre"]
        else:
            new_genre = meta["genre"]
            if not new_genre or new_genre.lower() == "unknown":
                new_genre = "Unknown"

        result = {
            "filepath": filepath,
            **existing_data_cache,
            "title": meta["title"],
            "artist": meta["artist"],
            "album": meta["album"],
            "genre": new_genre,
            "features_extra": {} 
        }
        return result
    except Exception as e:
        print(f"ERROR: Fast metadata update failed for {filename}: {e}")
        return None

async def process_track_ingestion(
    filepath: str, 
    force_update: bool,
    loop: asyncio.AbstractEventLoop,
    executor: Optional[Executor] = None,
    timeout: float = 300.0,
    db_lock: Optional[asyncio.Lock] = None,
    llm_sem: Optional[asyncio.Semaphore] = None,
    save_to_db: bool = True
) -> Optional[Dict[str, Any]]:
    """単一ファイルの解析とDB更新。排他制御付き。"""
    
    filename = os.path.basename(filepath)
    
    skip_basic = False
    skip_waveform = False
    metadata_update_only = False
    existing_data_cache = {}

    if not force_update:
        try:
            with Session(engine) as session:
                track = session.exec(select(Track).where(Track.filepath == filepath)).first()
                if track:
                    embedding = session.get(TrackEmbedding, track.id)
                    
                    # 共通ロジックを使用（Unknown判定の揺らぎを防止）
                    is_metadata_incomplete = not has_valid_metadata(track)

                    existing_data_cache = {
                        "bpm": track.bpm,
                        "key": track.key,
                        "scale": track.scale,
                        "energy": track.energy,
                        "danceability": track.danceability,
                        "brightness": track.brightness,
                        "contrast": track.contrast,
                        "noisiness": track.noisiness,
                        "loudness": track.loudness,
                        "loudness_range": track.loudness_range,
                        "spectral_flux": track.spectral_flux,
                        "spectral_rolloff": track.spectral_rolloff,
                        "duration": track.duration,
                        "genre": track.genre
                    }

                    if not embedding:
                        if is_metadata_incomplete:
                            skip_basic = False
                            skip_waveform = True # 波形生成はスキップ(高速化)
                            print(f"INFO: {filename} - Missing embedding & incomplete metadata. Running analysis (skipping waveform).")
                        else:
                            skip_basic = True
                            skip_waveform = True
                            print(f"INFO: {filename} - Track exists but missing embedding. Running lightweight analysis.")
                    
                    elif is_metadata_incomplete:
                        metadata_update_only = True
                        print(f"INFO: {filename} - FAST UPDATE: Metadata incomplete but analysis exists. Reading tags only.")
                    
                    else:
                        # メタデータの変更チェック
                        if check_metadata_changed(filepath, track):
                            metadata_update_only = True
                            print(f"INFO: {filename} - Metadata changed. Updating.")
                        else:
                            return None
                        
        except Exception as e:
            print(f"WARNING: DB check failed for {filename}: {e}")

    # --- パス A: メタデータのみ高速更新 (オーディオ解析なし) ---
    if metadata_update_only:
        result = await loop.run_in_executor(None, _process_metadata_update, filepath, existing_data_cache)
        
        if result and save_to_db:
            if db_lock:
                async with db_lock:
                    await save_to_db(result, result["genre"], filepath, update_metadata=True)
            else:
                await save_to_db(result, result["genre"], filepath, update_metadata=True)
            
        return result

    # --- パス B: 通常/軽量解析 (オーディオ解析あり) ---
    try:
        result = await asyncio.wait_for(
            loop.run_in_executor(executor, analyze_track_file, filepath, force_update, skip_basic, skip_waveform),
            timeout=timeout
        )
    except asyncio.TimeoutError:
        print(f"ERROR: Timeout processing {filename} (>{timeout}s)")
        return None
    except Exception as e:
        print(f"ERROR: Exception during analysis of {filepath}: {e}")
        return None
    
    if result:
        # メタデータをスマート補完 (Unknown対策)
        if result.get("artist") == "Unknown" or result.get("title") == "Unknown" or result.get("genre") == "Unknown":
             meta_smart = extract_metadata_smart(filepath)
             if result.get("artist") == "Unknown": result["artist"] = meta_smart["artist"]
             if result.get("title") == "Unknown" or result.get("title") == os.path.basename(filepath): 
                 result["title"] = meta_smart["title"]
             if result.get("genre") == "Unknown": result["genre"] = meta_smart["genre"]

        if skip_basic and existing_data_cache:
            result.update(existing_data_cache)
        
        if skip_basic:
            if "embedding" not in result:
                print(f"WARNING: Embedding generation failed for {filename}. Marking as empty to prevent loop.")
                result["embedding"] = [] 
                result["embedding_model"] = "failed"

            current_result_genre = result.get("genre")
            
            if not force_update and existing_data_cache.get("genre") and existing_data_cache["genre"].lower() != "unknown":
                result["genre"] = existing_data_cache["genre"]
            elif (not current_result_genre or current_result_genre == "Unknown") and existing_data_cache.get("genre"):
                 result["genre"] = existing_data_cache["genre"]

            if save_to_db:
                if db_lock:
                    async with db_lock:
                        await save_to_db(result, result.get("genre", "Unknown"), filepath, update_metadata=True)
                else:
                    await save_to_db(result, result.get("genre", "Unknown"), filepath, update_metadata=True)
            return result

        final_genre = result.get("genre", "Unknown")
        
        if not force_update and existing_data_cache.get("genre") and existing_data_cache["genre"].lower() != "unknown":
            final_genre = existing_data_cache["genre"]
        elif (not final_genre or final_genre == "Unknown") and existing_data_cache.get("genre"):
             final_genre = existing_data_cache["genre"]

        if save_to_db:
            if db_lock:
                async with db_lock:
                    await save_to_db(result, final_genre, filepath, update_metadata=True)
            else:
                await save_to_db(result, final_genre, filepath, update_metadata=True)
        
        return result
    
    return None

