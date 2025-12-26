import csv
import io
import json
import logging
import unicodedata
from typing import List, Dict, Any, Optional, Tuple
from sqlmodel import Session, select, text
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

    def _normalize_path(self, path: str) -> str:
        return unicodedata.normalize('NFC', path.strip()) if path else ""

    def _parse_csv_content(self, csv_content: str) -> csv.DictReader:
        if csv_content.startswith('\ufeff'): csv_content = csv_content[1:]
        return csv.DictReader(io.StringIO(csv_content))

    def _apply_track_metadata_safely(self, track: Track, data: Dict[str, Any]) -> bool:
        has_changes = False
        string_fields = ["title", "artist", "album", "genre", "subgenre", "key"]
        for field in string_fields:
            val = data.get(field)
            if val is not None:
                cleaned_val = str(val).strip()
                if cleaned_val and cleaned_val.lower() != "unknown":
                    if getattr(track, field) != cleaned_val:
                        setattr(track, field, cleaned_val)
                        has_changes = True
        
        year = data.get("year")
        if year and isinstance(year, int) and year > 0 and track.year != year:
            track.year, has_changes = year, True
        
        bpm = data.get("bpm")
        if bpm and isinstance(bpm, (float, int)) and bpm > 0 and track.bpm != bpm:
            track.bpm, has_changes = float(bpm), True
            
        verified = data.get("is_genre_verified")
        if verified is not None and track.is_genre_verified != verified:
            track.is_genre_verified, has_changes = verified, True

        audio_features = ["energy", "danceability", "brightness", "loudness", "noisiness", "contrast"]
        for feat in audio_features:
            val = data.get(feat)
            if val is not None:
                try:
                    f_val = float(val)
                    if getattr(track, feat) != f_val:
                        setattr(track, feat, f_val)
                        has_changes = True
                except: continue
        return has_changes

    def execute_metadata_import(self, req: MetadataImportExecuteRequest) -> int:
        updated_count = 0
        # DuckDB PRAGMA foreign_keys を削除し、no_autoflush のみで運用
        with self.session.no_autoflush:
            for update_item in req.updates:
                data = update_item.get("new") or update_item.get("data")
                if not data: continue
                filepath = data.get("filepath")
                norm_path = self._normalize_path(filepath)
                track = self.session.exec(select(Track).where(Track.filepath == norm_path)).first()
                if track and self._apply_track_metadata_safely(track, data):
                    self.session.add(track)
                    updated_count += 1
        self.session.commit()
        return updated_count

    def execute_import(self, data: ImportExecuteRequest) -> Tuple[int, int]:
        import_count, update_count = 0, 0
        with self.session.no_autoflush:
            for update_item in data.path_updates:
                old_path, new_path, track_data = update_item.get("old_path"), update_item.get("new_path"), update_item.get("track")
                track = self.session.exec(select(Track).where(Track.filepath == old_path)).first()
                if track:
                    track.filepath = new_path
                    if track_data and self._apply_track_metadata_safely(track, track_data):
                        self.session.add(track)
                        analysis = self.session.get(TrackAnalysis, track.id) or TrackAnalysis(track_id=track.id)
                        analysis.features_extra_json = json.dumps({
                            "bpm_confidence": track_data.get("bpm_confidence", 0.0),
                            "key_strength": track_data.get("key_strength", 0.0),
                            "bpm_raw": track_data.get("bpm_raw", 0.0)
                        })
                        if "beat_positions" in track_data: analysis.beat_positions = track_data["beat_positions"]
                        if "waveform_peaks" in track_data: analysis.waveform_peaks = track_data["waveform_peaks"]
                        self.session.add(analysis)
                    update_count += 1
                    
            for row in data.new_tracks:
                norm_path = self._normalize_path(row.filepath)
                if self.session.exec(select(Track).where(Track.filepath == norm_path)).first(): continue
                t_dict = row.model_dump()
                analysis_info = {
                    "extras": json.dumps({
                        "bpm_confidence": t_dict.pop("bpm_confidence", 0.0),
                        "key_strength": t_dict.pop("key_strength", 0.0),
                        "bpm_raw": t_dict.pop("bpm_raw", 0.0)
                    }),
                    "beats": t_dict.pop("beat_positions", []), "peaks": t_dict.pop("waveform_peaks", [])
                }
                if not t_dict.get("title"): t_dict["title"] = "Unknown"
                if not t_dict.get("artist"): t_dict["artist"] = "Unknown"
                track = Track(**t_dict)
                self.session.add(track)
                self.session.flush()
                self.session.add(TrackAnalysis(track_id=track.id, beat_positions=analysis_info["beats"], waveform_peaks=analysis_info["peaks"], features_extra_json=analysis_info["extras"]))
                import_count += 1
        self.session.commit()
        return import_count, update_count

    # 他の export / analyze メソッドは前回提示の「CSV App Service Refined」と同様...
    def export_metadata_csv(self) -> str:
        tracks = self.session.exec(select(Track)).all()
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["filepath", "title", "artist", "album", "genre", "subgenre", "year", "is_genre_verified"])
        for track in tracks:
            writer.writerow([track.filepath, track.title, track.artist, track.album, track.genre, track.subgenre, track.year, track.is_genre_verified])
        return output.getvalue()

    def analyze_metadata_import(self, csv_content: str) -> MetadataImportAnalysisResult:
        reader = self._parse_csv_content(csv_content)
        existing_tracks = self.session.exec(select(Track)).all()
        path_map = {self._normalize_path(t.filepath): t for t in existing_tracks}
        updates, not_found = [], []
        for row in reader:
            raw_path = row.get('filepath', '')
            norm_path = self._normalize_path(raw_path)
            if not norm_path: continue
            is_verified = row.get('is_genre_verified', '').lower() in ('true', '1', 'yes', 'on') if row.get('is_genre_verified') else None
            import_row = MetadataImportRow(filepath=raw_path, title=row.get('title'), artist=row.get('artist'), album=row.get('album'), genre=row.get('genre'), subgenre=row.get('subgenre'), year=int(row.get('year')) if row.get('year') and str(row.get('year')).isdigit() else None, is_genre_verified=is_verified)
            if norm_path in path_map:
                current_track = path_map[norm_path]
                dummy_track = Track(filepath=norm_path)
                for field in ["title", "artist", "album", "genre", "subgenre", "year", "is_genre_verified"]:
                    setattr(dummy_track, field, getattr(current_track, field))
                if self._apply_track_metadata_safely(dummy_track, import_row.model_dump()):
                    updates.append({"current": current_track, "new": import_row})
            else: not_found.append(import_row)
        return MetadataImportAnalysisResult(total_rows=len(updates) + len(not_found), updates=updates, not_found=not_found)

    def export_tracks_to_csv(self) -> str:
        query = select(Track, TrackAnalysis).join(TrackAnalysis, Track.id == TrackAnalysis.track_id, isouter=True)
        results = self.session.exec(query).all()
        output = io.StringIO()
        writer = csv.writer(output)
        headers = ["filepath", "title", "artist", "album", "genre", "subgenre", "year", "bpm", "key", "energy", "danceability", "brightness", "loudness", "noisiness", "contrast", "duration", "loudness_range", "spectral_flux", "spectral_rolloff", "bpm_confidence", "key_strength", "bpm_raw", "beat_positions", "waveform_peaks"]
        writer.writerow(headers)
        for track, analysis in results:
            extras = analysis.features_extra if analysis else {}
            writer.writerow([track.filepath, track.title, track.artist, track.album, track.genre, track.subgenre, track.year, track.bpm, track.key, track.energy, track.danceability, track.brightness, track.loudness, track.noisiness, track.contrast, track.duration, track.loudness_range, track.spectral_flux, track.spectral_rolloff, extras.get("bpm_confidence", ""), extras.get("key_strength", ""), extras.get("bpm_raw", ""), json.dumps(analysis.beat_positions) if analysis else "[]", json.dumps(analysis.waveform_peaks) if analysis else "[]"])
        return output.getvalue()

    def analyze_csv_import(self, csv_content: str) -> ImportAnalysisResult:
        reader = self._parse_csv_content(csv_content)
        existing_tracks = self.session.exec(select(Track)).all()
        path_map = {self._normalize_path(t.filepath): t for t in existing_tracks}
        meta_map = {}
        for t in existing_tracks:
            if t.title and t.artist:
                key = (t.title.lower().strip(), t.artist.lower().strip())
                meta_map.setdefault(key, []).append(t)
        new_tracks, duplicates, path_updates = [], [], []
        matched_original_ids = set()
        for row in reader:
            try:
                def safe_f(v): return float(v) if v else 0.0
                def safe_j(v): 
                    try: return json.loads(v) if v else []
                    except: return []
                import_row = CsvImportRow(filepath=row.get('filepath', ''), title=row.get('title', ''), artist=row.get('artist', ''), album=row.get('album', ''), genre=row.get('genre', ''), subgenre=row.get('subgenre', ''), year=int(row.get('year')) if row.get('year') and str(row.get('year')).isdigit() else None, bpm=safe_f(row.get('bpm')), key=row.get('key', ''), energy=safe_f(row.get('energy')), danceability=safe_f(row.get('danceability')), brightness=safe_f(row.get('brightness')), loudness=safe_f(row.get('loudness')), noisiness=safe_f(row.get('noisiness')), contrast=safe_f(row.get('contrast')), duration=safe_f(row.get('duration')), loudness_range=safe_f(row.get('loudness_range')), spectral_flux=safe_f(row.get('spectral_flux')), spectral_rolloff=safe_f(row.get('spectral_rolloff')), bpm_confidence=safe_f(row.get('bpm_confidence')), key_strength=safe_f(row.get('key_strength')), bpm_raw=safe_f(row.get('bpm_raw')), beat_positions=safe_j(row.get('beat_positions')), waveform_peaks=safe_j(row.get('waveform_peaks')))
            except: continue
            norm_path = self._normalize_path(import_row.filepath)
            if not norm_path: continue
            if norm_path in path_map: duplicates.append(import_row); continue
            meta_key = (import_row.title.lower().strip(), import_row.artist.lower().strip())
            candidates = meta_map.get(meta_key)
            found_move = False
            if candidates:
                for original in candidates:
                    if original.id not in matched_original_ids:
                        path_updates.append({"old_path": original.filepath, "new_path": import_row.filepath, "track": import_row.model_dump(), "original_id": original.id})
                        matched_original_ids.add(original.id); found_move = True; break
            if not found_move: new_tracks.append(import_row)
        return ImportAnalysisResult(total_rows=0, new_tracks=new_tracks, duplicates=duplicates, path_updates=path_updates)

    def _create_or_update_prompt(self, name: str, content: str, prompt_id: Optional[int] = None) -> int:
        if prompt_id:
            p = self.session.get(Prompt, prompt_id)
            if p: p.content = content; self.session.add(p); return p.id
        new_p = Prompt(name=f"Imported: {name}", content=content, is_default=False)
        self.session.add(new_p); self.session.commit(); self.session.refresh(new_p); return new_p.id

    def export_presets_csv(self) -> str:
        presets = self.session.exec(select(Preset)).all()
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["name", "description", "preset_type", "prompt_content"])
        for p in presets:
            prompt = self.session.get(Prompt, p.prompt_id) if p.prompt_id else None
            writer.writerow([p.name, p.description or "", p.preset_type, prompt.content if prompt else ""])
        return output.getvalue()

    def analyze_presets_import(self, csv_content: str) -> PresetImportAnalysisResult:
        reader = self._parse_csv_content(csv_content)
        existing = self.session.exec(select(Preset)).all()
        p_map = {p.name: p for p in existing}
        new_p, updates, dups = [], [], []
        for row in reader:
            name = row.get('name', '').strip()
            if not name: continue
            import_row = PresetImportRow(name=name, description=row.get('description', ''), preset_type=row.get('preset_type', 'all'), filters_json="{}", prompt_content=row.get('prompt_content', ''))
            if name in p_map:
                curr = p_map[name]; prompt = self.session.get(Prompt, curr.prompt_id) if curr.prompt_id else None
                curr_c = prompt.content if prompt else ""
                if (import_row.description != (curr.description or "") or import_row.preset_type != curr.preset_type or import_row.prompt_content != curr_c):
                    updates.append({"current": {"name": curr.name, "description": curr.description, "preset_type": curr.preset_type, "prompt_content": curr_c}, "new": import_row})
                else: dups.append(import_row)
            else: new_p.append(import_row)
        return PresetImportAnalysisResult(total_rows=len(new_p)+len(updates)+len(dups), new_presets=new_p, updates=updates, duplicates=dups)

    def execute_presets_import(self, req: PresetImportExecuteRequest) -> int:
        count = 0
        all_items = [(p, True) for p in req.new_presets] + [(PresetImportRow(**u["new"]), False) for u in req.updates]
        for p_data, is_new in all_items:
            if is_new:
                pid = self._create_or_update_prompt(p_data.name, p_data.prompt_content or "")
                self.session.add(Preset(name=p_data.name, description=p_data.description, preset_type=p_data.preset_type, filters_json=p_data.filters_json, prompt_id=pid))
            else:
                ex = self.session.exec(select(Preset).where(Preset.name == p_data.name)).first()
                if ex: ex.description, ex.preset_type = p_data.description, p_data.preset_type; ex.prompt_id = self._create_or_update_prompt(p_data.name, p_data.prompt_content or "", ex.prompt_id); self.session.add(ex)
            count += 1
        self.session.commit()
        return count