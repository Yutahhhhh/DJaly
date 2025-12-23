import os
import asyncio
import re
import json
from typing import List, Dict, Any, Optional
from concurrent.futures import Executor
from sqlmodel import Session, select
from tinytag import TinyTag
from ingest import analyze_track_file
from domain.constants import SUPPORTED_EXTENSIONS
from utils.metadata import extract_metadata_smart, check_metadata_changed, update_file_metadata
from utils.ingestion import has_valid_metadata
import infra.database.connection as db_connection
from domain.models.track import Track, TrackEmbedding
from infra.repositories.ingestion_repository import IngestionRepository

class IngestionDomainService:
    def __init__(self):
        self.repository = IngestionRepository()

    def _clean_llm_response(self, text: str) -> str:
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

    def _process_metadata_update(self, filepath: str, existing_data_cache: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        filename = os.path.basename(filepath)
        try:
            tag = TinyTag.get(filepath)
            meta = extract_metadata_smart(filepath, tag)
            
            print(f"DEBUG: Metadata extracted for {filename}: Artist='{meta.get('artist')}', Title='{meta.get('title')}'")

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
                "year": meta.get("year"),
                "features_extra": {} 
            }
            return result
        except Exception as e:
            print(f"ERROR: Fast metadata update failed for {filename}: {e}")
            return None

    async def process_track_ingestion(
        self,
        filepath: str, 
        force_update: bool,
        loop: asyncio.AbstractEventLoop,
        executor: Optional[Executor] = None,
        timeout: float = 300.0,
        db_lock: Optional[asyncio.Lock] = None,
        save_to_db: bool = True
    ) -> Optional[Dict[str, Any]]:
        
        filename = os.path.basename(filepath)

        # Check for .lrc file and import lyrics if present
        lrc_path = os.path.splitext(filepath)[0] + ".lrc"
        if os.path.exists(lrc_path):
            try:
                with open(lrc_path, 'r', encoding='utf-8') as f:
                    lyrics_content = f.read()
                if lyrics_content:
                    # Run in default executor (thread pool) to avoid blocking
                    await loop.run_in_executor(None, update_file_metadata, filepath, lyrics_content)
                    print(f"DEBUG: Imported lyrics from {os.path.basename(lrc_path)}")
            except Exception as e:
                print(f"WARNING: Failed to import .lrc file for {filename}: {e}")
        
        skip_basic = False
        skip_waveform = False
        metadata_update_only = False
        existing_data_cache = {}

        if not force_update:
            try:
                with Session(db_connection.engine) as session:
                    track = session.exec(select(Track).where(Track.filepath == filepath)).first()
                    if track:
                        embedding = session.get(TrackEmbedding, track.id)
                        
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
                            "genre": track.genre,
                            "year": track.year
                        }

                        if not embedding:
                            # Optimization: Check if file has valid metadata to avoid full analysis
                            if is_metadata_incomplete:
                                try:
                                    # Quick check of file tags
                                    tag_check = TinyTag.get(filepath)
                                    meta_check = extract_metadata_smart(filepath, tag_check)
                                    # If file has valid artist/title, we can skip full analysis
                                    if meta_check["artist"] != "Unknown" and meta_check["title"] != "Unknown":
                                        is_metadata_incomplete = False
                                        # Update cache to ensure we save the new metadata
                                        existing_data_cache.update(meta_check)
                                        print(f"INFO: {filename} - Found valid metadata in file. Upgrading to lightweight analysis.")
                                except Exception as e:
                                    print(f"DEBUG: Metadata check failed: {e}")

                            if is_metadata_incomplete:
                                skip_basic = False
                                skip_waveform = True 
                                print(f"INFO: {filename} - Missing embedding & incomplete metadata. Running analysis (skipping waveform).")
                            else:
                                skip_basic = True
                                skip_waveform = True
                                print(f"INFO: {filename} - Track exists but missing embedding. Running lightweight analysis.")
                        
                        elif is_metadata_incomplete:
                            metadata_update_only = True
                            print(f"INFO: {filename} - FAST UPDATE: Metadata incomplete but analysis exists. Reading tags only.")
                        
                        else:
                            if check_metadata_changed(filepath, track):
                                metadata_update_only = True
                                print(f"INFO: {filename} - Metadata changed. Updating.")
                            else:
                                return None
                            
            except Exception as e:
                print(f"WARNING: DB check failed for {filename}: {e}")

        if metadata_update_only:
            result = await loop.run_in_executor(None, self._process_metadata_update, filepath, existing_data_cache)
            
            if result and save_to_db:
                if db_lock:
                    async with db_lock:
                        await loop.run_in_executor(None, self.repository.save_track, result, True)
                else:
                    await loop.run_in_executor(None, self.repository.save_track, result, True)
            
            return result

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
            if result.get("artist") == "Unknown" or result.get("title") == "Unknown" or result.get("genre") == "Unknown":
                 meta_smart = extract_metadata_smart(filepath)
                 if result.get("artist") == "Unknown": result["artist"] = meta_smart["artist"]
                 if result.get("title") == "Unknown" or result.get("title") == os.path.basename(filepath): 
                     result["title"] = meta_smart["title"]
                 if result.get("genre") == "Unknown": result["genre"] = meta_smart["genre"]

            if skip_basic and existing_data_cache:
                # DBの値を優先するが、DBが空でresult(ファイル)に値がある場合はresultを生かす
                # 単純な update() だと DB=None, File=2000 のときに None で上書きされてしまうため、
                # DBに有効な値がある場合のみ上書きする。
                for key, db_val in existing_data_cache.items():
                    if db_val is not None and db_val != "":
                        result[key] = db_val
            
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
                            await loop.run_in_executor(None, self.repository.save_track, result, True)
                    else:
                        await loop.run_in_executor(None, self.repository.save_track, result, True)
                return result

            final_genre = result.get("genre", "Unknown")
            
            if not force_update and existing_data_cache.get("genre") and existing_data_cache["genre"].lower() != "unknown":
                final_genre = existing_data_cache["genre"]
            elif (not final_genre or final_genre == "Unknown") and existing_data_cache.get("genre"):
                 final_genre = existing_data_cache["genre"]

            if save_to_db:
                if db_lock:
                    async with db_lock:
                        await loop.run_in_executor(None, self.repository.save_track, result, True)
                else:
                    await loop.run_in_executor(None, self.repository.save_track, result, True)
            
            return result
        
        return None
