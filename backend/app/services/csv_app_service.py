import csv
import io
import json
import logging
import unicodedata
from typing import List, Dict, Any
from sqlmodel import Session, select
from sqlalchemy import update
from domain.models.track import Track, TrackAnalysis
from domain.models.preset import Preset
from domain.models.prompt import Prompt
from api.schemas.settings import (
    CsvImportRow, ImportAnalysisResult, ImportExecuteRequest,
    MetadataImportRow, MetadataImportAnalysisResult, MetadataImportExecuteRequest,
    PresetImportRow, PresetImportAnalysisResult, PresetImportExecuteRequest
)

logger = logging.getLogger(__name__)

class CsvAppService:
    def __init__(self, session: Session):
        self.session = session

    def _parse_csv_content(self, csv_content: str) -> csv.DictReader:
        if csv_content.startswith('\ufeff'):
            csv_content = csv_content[1:]
        return csv.DictReader(io.StringIO(csv_content))

    def _create_or_update_prompt(self, name: str, content: str, prompt_id: int = None) -> int:
        if prompt_id:
            prompt = self.session.get(Prompt, prompt_id)
            if prompt:
                prompt.content = content
                self.session.add(prompt)
                return prompt.id
                
        new_prompt = Prompt(
            name=f"Imported: {name}",
            content=content,
            is_default=False
        )
        self.session.add(new_prompt)
        self.session.commit()
        self.session.refresh(new_prompt)
        return new_prompt.id

    def export_metadata_csv(self) -> str:
        tracks = self.session.exec(select(Track)).all()
        
        output = io.StringIO()
        writer = csv.writer(output)
        
        headers = ["filepath", "title", "artist", "album", "genre", "subgenre", "year", "is_genre_verified"]
        writer.writerow(headers)
        
        for track in tracks:
            writer.writerow([
                track.filepath,
                track.title,
                track.artist,
                track.album,
                track.genre,
                track.subgenre,
                track.year,
                track.is_genre_verified
            ])
            
        return output.getvalue()

    def analyze_metadata_import(self, csv_content: str) -> MetadataImportAnalysisResult:
        reader = self._parse_csv_content(csv_content)
        
        # Helper for path normalization (NFC for macOS compatibility)
        def normalize_path(p: str) -> str:
            return unicodedata.normalize('NFC', p) if p else ""
        
        existing_tracks = self.session.exec(select(Track)).all()
        path_map = {normalize_path(t.filepath): t for t in existing_tracks}
        
        updates = []
        not_found = []
        
        for row in reader:
            filepath = row.get('filepath', '').strip()
            if not filepath:
                continue
                
            normalized_filepath = normalize_path(filepath)
            
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
                subgenre=row.get('subgenre'),
                year=int(row.get('year')) if row.get('year') else None,
                is_genre_verified=is_verified
            )
            
            if normalized_filepath in path_map:
                current_track = path_map[normalized_filepath]
                has_changes = False
                
                # Helper to normalize strings for comparison (None -> "")
                def norm(s): return (s or "").strip()
                
                if import_row.title is not None and norm(import_row.title) != norm(current_track.title): has_changes = True
                if import_row.artist is not None and norm(import_row.artist) != norm(current_track.artist): has_changes = True
                if import_row.album is not None and norm(import_row.album) != norm(current_track.album): has_changes = True
                if import_row.genre is not None and norm(import_row.genre) != norm(current_track.genre): has_changes = True
                if import_row.subgenre is not None and norm(import_row.subgenre) != norm(current_track.subgenre): has_changes = True
                if import_row.year is not None and import_row.year != current_track.year: has_changes = True
                if import_row.is_genre_verified is not None and import_row.is_genre_verified != current_track.is_genre_verified: has_changes = True
                
                if has_changes:
                    updates.append({
                        "current": current_track,
                        "new": import_row
                    })
            else:
                not_found.append(import_row)
                
        return MetadataImportAnalysisResult(
            total_rows=len(updates) + len(not_found),
            updates=updates,
            not_found=not_found
        )

    def execute_metadata_import(self, req: MetadataImportExecuteRequest) -> int:
        if not req.updates:
            return 0

        # Helper for path normalization
        def normalize_path(p: str) -> str:
            return unicodedata.normalize('NFC', p) if p else ""

        # 1. Collect all filepaths from request
        update_map = {} # normalized_path -> data
        for update_item in req.updates:
            # Frontend sends { "current": ..., "new": ... } from analysis result
            # We need to extract 'new' which contains the MetadataImportRow data
            data = update_item.get("new")
            
            # Fallback if the structure is different (e.g. { "filepath":..., "data":... })
            if not data:
                data = update_item.get("data")
            
            if not data:
                continue
                
            filepath = data.get("filepath") or update_item.get("filepath")
            
            if filepath:
                update_map[normalize_path(filepath)] = data

        if not update_map:
            return 0

        # 2. Fetch all tracks to map filepath -> track objects
        all_tracks = self.session.exec(select(Track)).all()
        
        # 3. Update tracks individually (safer for DuckDB with foreign key constraints)
        updated_count = 0
        for track in all_tracks:
            norm_path = normalize_path(track.filepath)
            if norm_path in update_map:
                data = update_map[norm_path]
                
                # Only update fields that are present in data (not None)
                if data.get('title') is not None: 
                    track.title = data['title']
                if data.get('artist') is not None: 
                    track.artist = data['artist']
                if data.get('album') is not None: 
                    track.album = data['album']
                if data.get('genre') is not None: 
                    track.genre = data['genre']
                if data.get('subgenre') is not None: 
                    track.subgenre = data['subgenre']
                if data.get('year') is not None: 
                    track.year = data['year']
                if data.get('is_genre_verified') is not None: 
                    track.is_genre_verified = data['is_genre_verified']
                
                self.session.add(track)
                updated_count += 1

        # 4. Commit all changes
        if updated_count > 0:
            self.session.commit()
            
        return updated_count

    def export_tracks_to_csv(self) -> str:
        query = select(Track, TrackAnalysis).join(TrackAnalysis, Track.id == TrackAnalysis.track_id, isouter=True)
        results = self.session.exec(query).all()
        
        output = io.StringIO()
        writer = csv.writer(output)
        
        headers = [
            "filepath", "title", "artist", "album", "genre", "subgenre", "year",
            "bpm", "key", "energy", "danceability", "brightness", 
            "loudness", "noisiness", "contrast", "duration",
            "loudness_range", "spectral_flux", "spectral_rolloff",
            "bpm_confidence", "key_strength", "bpm_raw",
            "beat_positions", "waveform_peaks"
        ]
        writer.writerow(headers)
        
        for track, analysis in results:
            beat_positions = analysis.beat_positions if analysis else []
            waveform_peaks = analysis.waveform_peaks if analysis else []
            extras = analysis.features_extra if analysis else {}
            
            beats_json = json.dumps(beat_positions) if beat_positions else "[]"
            peaks_json = json.dumps(waveform_peaks) if waveform_peaks else "[]"

            writer.writerow([
                track.filepath, track.title, track.artist, track.album, track.genre, track.subgenre, track.year,
                track.bpm, track.key, track.energy, track.danceability, track.brightness,
                track.loudness, track.noisiness, track.contrast, track.duration,
                track.loudness_range, track.spectral_flux, track.spectral_rolloff,
                extras.get("bpm_confidence", ""),
                extras.get("key_strength", ""),
                extras.get("bpm_raw", ""),
                beats_json,
                peaks_json
            ])
            
        return output.getvalue()

    def analyze_csv_import(self, csv_content: str) -> ImportAnalysisResult:
        reader = self._parse_csv_content(csv_content)
        
        existing_tracks = self.session.exec(select(Track)).all()
        path_map = {t.filepath: t for t in existing_tracks}
        
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
                    subgenre=row.get('subgenre', ''),
                    year=int(row.get('year')) if row.get('year') else None,
                    bpm=safe_float(row.get('bpm')),
                    key=row.get('key', ''),
                    energy=safe_float(row.get('energy')),
                    danceability=safe_float(row.get('danceability')),
                    brightness=safe_float(row.get('brightness')),
                    loudness=safe_float(row.get('loudness')),
                    noisiness=safe_float(row.get('noisiness')),
                    contrast=safe_float(row.get('contrast')),
                    duration=safe_float(row.get('duration')),
                    loudness_range=safe_float(row.get('loudness_range')),
                    spectral_flux=safe_float(row.get('spectral_flux')),
                    spectral_rolloff=safe_float(row.get('spectral_rolloff')),
                    bpm_confidence=safe_float(row.get('bpm_confidence')),
                    key_strength=safe_float(row.get('key_strength')),
                    bpm_raw=safe_float(row.get('bpm_raw')),
                    beat_positions=safe_json_list(row.get('beat_positions')),
                    waveform_peaks=safe_json_list(row.get('waveform_peaks'))
                )
            except Exception as e:
                logger.warning(f"Skipping invalid row: {row} - {e}")
                continue

            if not import_row.filepath:
                continue

            if import_row.filepath in path_map:
                duplicates.append(import_row)
                continue
                
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
            
            if not path_update_found:
                new_tracks.append(import_row)

        return ImportAnalysisResult(
            total_rows=0, 
            new_tracks=new_tracks,
            duplicates=duplicates,
            path_updates=path_updates
        )

    def execute_import(self, data: ImportExecuteRequest):
        import_count = 0
        update_count = 0

        for update in data.path_updates:
            old_path = update.get("old_path")
            new_path = update.get("new_path")
            track_data = update.get("track")

            track = self.session.exec(select(Track).where(Track.filepath == old_path)).first()
            if track:
                track.filepath = new_path
                
                if track_data:
                    extras = {
                        "bpm_confidence": track_data.get("bpm_confidence", 0.0),
                        "key_strength": track_data.get("key_strength", 0.0),
                        "bpm_raw": track_data.get("bpm_raw", 0.0)
                    }
                    
                    for k, v in track_data.items():
                        if k in ["bpm_confidence", "key_strength", "bpm_raw", "filepath", "beat_positions", "waveform_peaks"]:
                            continue
                        if hasattr(track, k) and v is not None:
                            setattr(track, k, v)
                    
                    self.session.add(track)
                    self.session.commit()
                    self.session.refresh(track)

                    analysis = self.session.get(TrackAnalysis, track.id)
                    if not analysis:
                        analysis = TrackAnalysis(track_id=track.id)
                    
                    analysis.features_extra_json = json.dumps(extras)
                    if "beat_positions" in track_data:
                        analysis.beat_positions = track_data["beat_positions"]
                    if "waveform_peaks" in track_data:
                        analysis.waveform_peaks = track_data["waveform_peaks"]
                    
                    self.session.add(analysis)

                update_count += 1
                
        for new_track in data.new_tracks:
            existing = self.session.exec(select(Track).where(Track.filepath == new_track.filepath)).first()
            if not existing:
                t_data = new_track.model_dump()
                
                extras = {
                    "bpm_confidence": t_data.pop("bpm_confidence", 0.0),
                    "key_strength": t_data.pop("key_strength", 0.0),
                    "bpm_raw": t_data.pop("bpm_raw", 0.0)
                }
                beat_positions = t_data.pop("beat_positions", [])
                waveform_peaks = t_data.pop("waveform_peaks", [])
                
                track = Track(**t_data)
                self.session.add(track)
                self.session.commit()
                self.session.refresh(track)
                
                analysis = TrackAnalysis(
                    track_id=track.id,
                    beat_positions=beat_positions,
                    waveform_peaks=waveform_peaks,
                    features_extra_json=json.dumps(extras)
                )
                self.session.add(analysis)
                
                import_count += 1
                
        self.session.commit()
        return import_count, update_count

    def export_presets_csv(self) -> str:
        presets = self.session.exec(select(Preset)).all()
        output = io.StringIO()
        writer = csv.writer(output)
        
        headers = ["name", "description", "preset_type", "prompt_content"]
        writer.writerow(headers)
        
        for p in presets:
            prompt_content = ""
            if p.prompt_id:
                prompt = self.session.get(Prompt, p.prompt_id)
                if prompt:
                    prompt_content = prompt.content
                    
            writer.writerow([
                p.name,
                p.description or "",
                p.preset_type,
                prompt_content
            ])
            
        return output.getvalue()

    def analyze_presets_import(self, csv_content: str) -> PresetImportAnalysisResult:
        reader = self._parse_csv_content(csv_content)
        
        existing_presets = self.session.exec(select(Preset)).all()
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
                filters_json="{}", 
                prompt_content=row.get('prompt_content', '')
            )
            
            if name in preset_map:
                current = preset_map[name]
                current_prompt_content = ""
                if current.prompt_id:
                    prompt = self.session.get(Prompt, current.prompt_id)
                    if prompt:
                        current_prompt_content = prompt.content
                
                has_changes = False
                if import_row.description != (current.description or ""): has_changes = True
                if import_row.preset_type != current.preset_type: has_changes = True
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

    def execute_presets_import(self, req: PresetImportExecuteRequest) -> int:
        count = 0
        
        for p_data in req.new_presets:
            prompt_id = self._create_or_update_prompt(p_data.name, p_data.prompt_content or "")
            
            new_preset = Preset(
                name=p_data.name,
                description=p_data.description,
                preset_type=p_data.preset_type,
                filters_json=p_data.filters_json,
                prompt_id=prompt_id
            )
            self.session.add(new_preset)
            count += 1
            
        for update in req.updates:
            p_data = PresetImportRow(**update["new"])
            existing = self.session.exec(select(Preset).where(Preset.name == p_data.name)).first()
            if existing:
                existing.description = p_data.description
                existing.preset_type = p_data.preset_type
                
                if existing.prompt_id:
                    self._create_or_update_prompt(p_data.name, p_data.prompt_content or "", existing.prompt_id)
                else:
                    existing.prompt_id = self._create_or_update_prompt(p_data.name, p_data.prompt_content or "")
                    
                self.session.add(existing)
                count += 1
                
        self.session.commit()
        return count
