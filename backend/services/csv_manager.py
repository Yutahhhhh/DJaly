import csv
import io
import json
import logging
from typing import List, Dict, Any
from sqlmodel import Session, select
from models import Track, TrackAnalysis, Preset, Prompt
from schemas.settings import (
    CsvImportRow, ImportAnalysisResult, ImportExecuteRequest,
    MetadataImportRow, MetadataImportAnalysisResult, MetadataImportExecuteRequest,
    PresetImportRow, PresetImportAnalysisResult, PresetImportExecuteRequest
)

logger = logging.getLogger(__name__)

def _parse_csv_content(csv_content: str) -> csv.DictReader:
    """CSVコンテンツをパースしてDictReaderを返す（BOM対応）"""
    if csv_content.startswith('\ufeff'):
        csv_content = csv_content[1:]
    return csv.DictReader(io.StringIO(csv_content))

def _create_or_update_prompt(session: Session, name: str, content: str, prompt_id: int = None) -> int:
    """Promptを作成または更新し、IDを返す"""
    if prompt_id:
        prompt = session.get(Prompt, prompt_id)
        if prompt:
            prompt.content = content
            session.add(prompt)
            return prompt.id
            
    # Create new
    new_prompt = Prompt(
        name=f"Imported: {name}",
        content=content,
        is_default=False
    )
    session.add(new_prompt)
    session.commit()
    session.refresh(new_prompt)
    return new_prompt.id

def export_metadata_csv(session: Session) -> str:
    """メタデータ更新用の軽量CSVをエクスポート"""
    tracks = session.exec(select(Track)).all()
    
    output = io.StringIO()
    writer = csv.writer(output)
    
    headers = ["filepath", "title", "artist", "album", "genre", "is_genre_verified"]
    writer.writerow(headers)
    
    for track in tracks:
        writer.writerow([
            track.filepath,
            track.title,
            track.artist,
            track.album,
            track.genre,
            track.is_genre_verified
        ])
        
    return output.getvalue()

def analyze_metadata_import(session: Session, csv_content: str) -> MetadataImportAnalysisResult:
    """メタデータCSVを解析し、更新対象を特定する"""
    reader = _parse_csv_content(csv_content)
    
    # 高速検索用マップ
    existing_tracks = session.exec(select(Track)).all()
    path_map = {t.filepath: t for t in existing_tracks}
    
    updates = []
    not_found = []
    
    for row in reader:
        filepath = row.get('filepath', '').strip()
        if not filepath:
            continue
            
        # is_genre_verified のパース
        is_verified_raw = row.get('is_genre_verified')
        is_verified = None
        if is_verified_raw is not None and is_verified_raw != "":
            is_verified = str(is_verified_raw).lower() in ('true', '1', 'yes', 'on')

        import_row = MetadataImportRow(
            filepath=filepath,
            title=row.get('title'),
            artist=row.get('artist'),
            album=row.get('album'),
            genre=row.get('genre'),
            is_genre_verified=is_verified
        )
        
        if filepath in path_map:
            current_track = path_map[filepath]
            # 変更があるかチェック（簡易的）
            has_changes = False
            
            if import_row.title and import_row.title != current_track.title: has_changes = True
            if import_row.artist and import_row.artist != current_track.artist: has_changes = True
            if import_row.album and import_row.album != current_track.album: has_changes = True
            if import_row.genre and import_row.genre != current_track.genre: has_changes = True
            if import_row.is_genre_verified is not None and import_row.is_genre_verified != current_track.is_genre_verified: has_changes = True
            
            if has_changes:
                updates.append({
                    "filepath": filepath,
                    "current": {
                        "title": current_track.title,
                        "artist": current_track.artist,
                        "album": current_track.album,
                        "genre": current_track.genre,
                        "is_genre_verified": current_track.is_genre_verified
                    },
                    "new": import_row.dict()
                })
        else:
            not_found.append(import_row)
            
    return MetadataImportAnalysisResult(
        total_rows=len(updates) + len(not_found),
        updates=updates,
        not_found=not_found
    )

def execute_metadata_import(session: Session, data: MetadataImportExecuteRequest) -> int:
    """メタデータ更新を実行"""
    update_count = 0
    
    for item in data.updates:
        filepath = item.get("filepath")
        # analyzeの結果は "new" キーに入っている
        new_data = item.get("new") or item.get("data")
        
        if not filepath or not new_data:
            continue
            
        track = session.exec(select(Track).where(Track.filepath == filepath)).first()
        if track:
            if new_data.get("title") is not None: track.title = new_data["title"]
            if new_data.get("artist") is not None: track.artist = new_data["artist"]
            if new_data.get("album") is not None: track.album = new_data["album"]
            if new_data.get("genre") is not None: track.genre = new_data["genre"]
            if new_data.get("is_genre_verified") is not None: track.is_genre_verified = new_data["is_genre_verified"]
            
            session.add(track)
            update_count += 1
            
    session.commit()
    return update_count

def export_tracks_to_csv(session: Session) -> str:
    """全トラックをCSV文字列としてエクスポート"""
    # TrackとTrackAnalysisを結合して取得
    query = select(Track, TrackAnalysis).join(TrackAnalysis, Track.id == TrackAnalysis.track_id, isouter=True)
    results = session.exec(query).all()
    
    output = io.StringIO()
    writer = csv.writer(output)
    
    # Header
    headers = [
        "filepath", "title", "artist", "album", "genre", 
        "bpm", "key", "energy", "danceability", "brightness", 
        "loudness", "noisiness", "contrast", "duration",
        # Extended Features
        "loudness_range", "spectral_flux", "spectral_rolloff",
        "bpm_confidence", "key_strength", "bpm_raw",
        # Large Data (JSON serialized)
        "beat_positions", "waveform_peaks"
    ]
    writer.writerow(headers)
    
    for track, analysis in results:
        # Analysisデータが存在しない場合のハンドリング
        beat_positions = analysis.beat_positions if analysis else []
        waveform_peaks = analysis.waveform_peaks if analysis else []
        extras = analysis.features_extra if analysis else {}
        
        # 配列データはJSON文字列化してCSVに格納
        beats_json = json.dumps(beat_positions) if beat_positions else "[]"
        peaks_json = json.dumps(waveform_peaks) if waveform_peaks else "[]"

        writer.writerow([
            track.filepath, track.title, track.artist, track.album, track.genre,
            track.bpm, track.key, track.energy, track.danceability, track.brightness,
            track.loudness, track.noisiness, track.contrast, track.duration,
            # Extended Features
            track.loudness_range, track.spectral_flux, track.spectral_rolloff,
            extras.get("bpm_confidence", ""),
            extras.get("key_strength", ""),
            extras.get("bpm_raw", ""),
            # Large Data
            beats_json,
            peaks_json
        ])
        
    return output.getvalue()

def analyze_csv_import(session: Session, csv_content: str) -> ImportAnalysisResult:
    """
    CSVを解析し、DBとの差分（新規、重複、パス変更）を分類する。
    """
    reader = _parse_csv_content(csv_content)
    
    existing_tracks = session.exec(select(Track)).all()
    
    # 高速検索用マップ
    path_map = {t.filepath: t for t in existing_tracks}
    
    # メタデータ検索用マップ (Title + Artist -> Track)
    meta_map = {}
    for t in existing_tracks:
        if t.title and t.artist:
            key = (t.title.lower().strip(), t.artist.lower().strip())
            if key not in meta_map:
                meta_map[key] = []
            meta_map[key].append(t)

    new_tracks = []
    duplicates = []
    path_updates = []

    matched_original_ids = set()

    for row in reader:
        try:
            def safe_float(val, default=0.0):
                if not val: return default
                try: return float(val)
                except: return default
            
            def safe_json_list(val):
                if not val: return []
                try: 
                    parsed = json.loads(val)
                    if isinstance(parsed, list): return parsed
                    return []
                except: return []

            import_row = CsvImportRow(
                filepath=row.get('filepath', ''),
                title=row.get('title', ''),
                artist=row.get('artist', ''),
                album=row.get('album', ''),
                genre=row.get('genre', ''),
                bpm=safe_float(row.get('bpm')),
                key=row.get('key', ''),
                energy=safe_float(row.get('energy')),
                danceability=safe_float(row.get('danceability')),
                brightness=safe_float(row.get('brightness')),
                loudness=safe_float(row.get('loudness')),
                noisiness=safe_float(row.get('noisiness')),
                contrast=safe_float(row.get('contrast')),
                duration=safe_float(row.get('duration')),
                
                # Extended Features
                loudness_range=safe_float(row.get('loudness_range')),
                spectral_flux=safe_float(row.get('spectral_flux')),
                spectral_rolloff=safe_float(row.get('spectral_rolloff')),
                bpm_confidence=safe_float(row.get('bpm_confidence')),
                key_strength=safe_float(row.get('key_strength')),
                bpm_raw=safe_float(row.get('bpm_raw')),
                
                # Large Data
                beat_positions=safe_json_list(row.get('beat_positions')),
                waveform_peaks=safe_json_list(row.get('waveform_peaks'))
            )
        except Exception as e:
            logger.warning(f"Skipping invalid row: {row} - {e}")
            continue

        if not import_row.filepath:
            continue

        # 1. 完全一致
        if import_row.filepath in path_map:
            duplicates.append(import_row)
            continue
            
        # 2. パス移動検知
        meta_key = (import_row.title.lower().strip(), import_row.artist.lower().strip())
        candidates = meta_map.get(meta_key)
        
        path_update_found = False
        if candidates:
            for original_track in candidates:
                if original_track.id not in matched_original_ids:
                    path_updates.append({
                        "old_path": original_track.filepath,
                        "new_path": import_row.filepath,
                        "track": import_row,
                        "original_id": original_track.id
                    })
                    matched_original_ids.add(original_track.id)
                    path_update_found = True
                    break
        
        # 3. 新規
        if not path_update_found:
            new_tracks.append(import_row)

    return ImportAnalysisResult(
        total_rows=0, 
        new_tracks=new_tracks,
        duplicates=duplicates,
        path_updates=path_updates
    )

def execute_import(session: Session, data: ImportExecuteRequest):
    import_count = 0
    update_count = 0

    # 1. パス更新
    for update in data.path_updates:
        old_path = update.get("old_path")
        new_path = update.get("new_path")
        track_data = update.get("track") # This is a dict (CsvImportRow)

        track = session.exec(select(Track).where(Track.filepath == old_path)).first()
        if track:
            track.filepath = new_path
            
            # CSVデータで上書き
            if track_data:
                # Handle JSON fields for extras
                extras = {
                    "bpm_confidence": track_data.get("bpm_confidence", 0.0),
                    "key_strength": track_data.get("key_strength", 0.0),
                    "bpm_raw": track_data.get("bpm_raw", 0.0)
                }
                
                # Update standard & new columns
                for k, v in track_data.items():
                    if k in ["bpm_confidence", "key_strength", "bpm_raw", "filepath", "beat_positions", "waveform_peaks"]:
                        continue
                    if hasattr(track, k) and v is not None:
                        setattr(track, k, v)
                
                session.add(track)
                session.commit() # Commit to ensure track exists
                session.refresh(track)

                # Update Analysis Data
                analysis = session.get(TrackAnalysis, track.id)
                if not analysis:
                    analysis = TrackAnalysis(track_id=track.id)
                
                analysis.features_extra_json = json.dumps(extras)
                if "beat_positions" in track_data:
                    analysis.beat_positions = track_data["beat_positions"]
                if "waveform_peaks" in track_data:
                    analysis.waveform_peaks = track_data["waveform_peaks"]
                
                session.add(analysis)

            update_count += 1
            
    # 2. 新規追加
    for new_track in data.new_tracks:
        existing = session.exec(select(Track).where(Track.filepath == new_track.filepath)).first()
        if not existing:
            t_data = new_track.dict()
            
            # Extract heavy/extra data
            extras = {
                "bpm_confidence": t_data.pop("bpm_confidence", 0.0),
                "key_strength": t_data.pop("key_strength", 0.0),
                "bpm_raw": t_data.pop("bpm_raw", 0.0)
            }
            beat_positions = t_data.pop("beat_positions", [])
            waveform_peaks = t_data.pop("waveform_peaks", [])
            
            # Create Track
            track = Track(**t_data)
            session.add(track)
            session.commit()
            session.refresh(track)
            
            # Create Analysis
            analysis = TrackAnalysis(
                track_id=track.id,
                beat_positions=beat_positions,
                waveform_peaks=waveform_peaks,
                features_extra_json=json.dumps(extras)
            )
            session.add(analysis)
            
            import_count += 1
            
    session.commit()
    return import_count

def export_presets_csv(session: Session) -> str:
    """プリセットをCSVとしてエクスポート"""
    presets = session.exec(select(Preset)).all()
    output = io.StringIO()
    writer = csv.writer(output)
    
    headers = ["name", "description", "preset_type", "prompt_content"]
    writer.writerow(headers)
    
    for p in presets:
        prompt_content = ""
        if p.prompt_id:
            prompt = session.get(Prompt, p.prompt_id)
            if prompt:
                prompt_content = prompt.content
                
        writer.writerow([
            p.name,
            p.description or "",
            p.preset_type,
            prompt_content
        ])
        
    return output.getvalue()

def analyze_presets_import(session: Session, csv_content: str) -> PresetImportAnalysisResult:
    """プリセットCSVを解析"""
    reader = _parse_csv_content(csv_content)
    
    existing_presets = session.exec(select(Preset)).all()
    preset_map = {p.name: p for p in existing_presets}
    
    new_presets = []
    updates = []
    duplicates = []
    
    for row in reader:
        name = row.get('name', '').strip()
        if not name: continue
        
        import_row = PresetImportRow(
            name=name,
            description=row.get('description', ''),
            preset_type=row.get('preset_type', 'all'),
            filters_json="{}", # Default empty
            prompt_content=row.get('prompt_content', '')
        )
        
        if name in preset_map:
            current = preset_map[name]
            current_prompt_content = ""
            if current.prompt_id:
                prompt = session.get(Prompt, current.prompt_id)
                if prompt:
                    current_prompt_content = prompt.content
            
            has_changes = False
            if import_row.description != (current.description or ""): has_changes = True
            if import_row.preset_type != current.preset_type: has_changes = True
            # filters_json is ignored in CSV, so we don't check it for changes
            if import_row.prompt_content != current_prompt_content: has_changes = True
            
            if has_changes:
                updates.append({
                    "current": {
                        "name": current.name,
                        "description": current.description,
                        "preset_type": current.preset_type,
                        "filters_json": current.filters_json,
                        "prompt_content": current_prompt_content
                    },
                    "new": import_row
                })
            else:
                duplicates.append(import_row)
        else:
            new_presets.append(import_row)
            
    return PresetImportAnalysisResult(
        total_rows=len(new_presets) + len(updates) + len(duplicates),
        new_presets=new_presets,
        updates=updates,
        duplicates=duplicates
    )

def execute_presets_import(session: Session, req: PresetImportExecuteRequest) -> int:
    """プリセットインポートを実行"""
    count = 0
    
    # New Presets
    for p_data in req.new_presets:
        # Create Prompt
        prompt_id = _create_or_update_prompt(session, p_data.name, p_data.prompt_content or "")
        
        # Create Preset
        new_preset = Preset(
            name=p_data.name,
            description=p_data.description,
            preset_type=p_data.preset_type,
            filters_json=p_data.filters_json,
            prompt_id=prompt_id
        )
        session.add(new_preset)
        count += 1
        
    # Updates
    for update in req.updates:
        p_data = PresetImportRow(**update["new"])
        existing = session.exec(select(Preset).where(Preset.name == p_data.name)).first()
        if existing:
            existing.description = p_data.description
            existing.preset_type = p_data.preset_type
            # filters_json is not updated from CSV
            
            # Update Prompt
            if existing.prompt_id:
                _create_or_update_prompt(session, p_data.name, p_data.prompt_content or "", existing.prompt_id)
            else:
                existing.prompt_id = _create_or_update_prompt(session, p_data.name, p_data.prompt_content or "")
                
            session.add(existing)
            count += 1
            
    session.commit()
    return count
    return import_count, update_count