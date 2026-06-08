from typing import List, Optional, Dict, Any
from sqlmodel import Session
import json
import re
from collections import defaultdict

from domain.models.track import Track
from domain.models.lyrics import Lyrics
from infra.repositories.genre_repository import GenreRepository
from infra.repositories.track_repository import TrackRepository
from api.schemas.genres import (
    GenreAnalysisResponse, 
    GenreBatchUpdateRequest, 
    GenreCleanupGroup, 
    TrackSuggestion,
    GenreUpdateResult,
    AnalysisMode
)
from utils.llm import generate_text, is_llm_error
from utils.metadata import update_file_genre, update_file_tags_extended
from utils.logger import get_logger
from domain.constants import GENRE_ABBREVIATIONS, GENRE_SEPARATORS_REGEX

logger = get_logger(__name__)

DJ_GENRE_GUIDE = """
DJ library taxonomy:
- Use the best-known public/catalog genre for the exact track when the title and artist are recognizable.
- Use one concise main genre and one concise subgenre when available.
- Do not choose a vague umbrella label when a more recognized specific genre is clearly known.
- Do not restrict yourself to any fixed genre list.
""".strip()

GENRE_ALIASES = {
    "hip hop": "Hip-Hop",
    "hip-hop": "Hip-Hop",
    "rap": "Hip-Hop",
    "rnb": "R&B",
    "r&b": "R&B",
    "r and b": "R&B",
    "afrobeat": "Afrobeats",
    "afrobeats": "Afrobeats",
    "afro beats": "Afrobeats",
    "amapiano": "Amapiano",
    "reggae": "Reggae",
    "dancehall": "Dancehall",
    "reggaeton": "Reggaeton",
    "latin": "Latin",
    "latin pop": "Latin",
    "pop": "Pop",
}

SUBGENRE_ALIASES = {
    "contemporary r&b": "Contemporary R&B",
    "contemporary rnb": "Contemporary R&B",
    "crunk&b": "Crunk&B",
    "crunk b": "Crunk&B",
    "trap soul": "Trap Soul",
    "afro pop": "Afropop",
    "afropop": "Afropop",
    "popiano": "Popiano",
}

class GenreAppService:
    def __init__(self, session: Session):
        self.session = session
        self.repository = GenreRepository(session)
        self.track_repository = TrackRepository(session)

    def get_unknown_tracks(self, offset: int = 0, limit: int = 50, mode: AnalysisMode = AnalysisMode.GENRE) -> List[Track]:
        return self.repository.get_unknown_tracks(offset, limit, mode=mode.value if hasattr(mode, 'value') else mode)

    def get_all_unknown_track_ids(self, mode: AnalysisMode = AnalysisMode.GENRE) -> List[int]:
        return self.repository.get_all_unknown_track_ids(mode=mode.value if hasattr(mode, 'value') else mode)

    def get_all_genres(self) -> List[str]:
        """Get all unique genres"""
        return self.repository.get_all_genres()

    def get_all_subgenres(self) -> List[str]:
        """Get all unique subgenres"""
        return self.repository.get_all_subgenres()

    def analyze_track_with_llm(self, track_id: int, overwrite: bool = False, mode: AnalysisMode = AnalysisMode.BOTH) -> GenreAnalysisResponse:
        track = self.track_repository.get_by_id(track_id)
        if not track:
            raise ValueError("Track not found")
        
        bpm_str = f"{int(track.bpm)}" if track.bpm and track.bpm > 0 else "Unknown"
        
        prompt = f"""
        Analyze metadata to determine music genre for a DJ music library.
        Track: {track.title} / {track.artist} (BPM: {bpm_str})
        
        Mode: {mode.value.upper()}

        {DJ_GENRE_GUIDE}
        """

        if mode == AnalysisMode.GENRE:
            prompt += """
            Output JSON: {"genre": "Main Category", "reason": "short reason", "confidence": "High/Medium/Low"}
            """
        elif mode == AnalysisMode.SUBGENRE:
            prompt += """
            Output JSON: {"subgenre": "Specific Style", "reason": "short reason", "confidence": "High/Medium/Low"}
            """
        else:
            prompt += """
            Output JSON: {"genre": "Main Category", "subgenre": "Specific Style", "reason": "short reason", "confidence": "High/Medium/Low"}
            """

        prompt += """
        Rules:
        - Use standard genres.
        - No "Intro", "Clean" etc.
        - Output only ONE single genre/subgenre. Do NOT use slashes (/) or commas (,).
        - If multiple genres apply, choose the most dominant one.
        - JSON ONLY.
        """
        
        raw_response = generate_text(self.session, prompt)
        
        if is_llm_error(raw_response):
            logger.error(f"Single Analysis Failed: {raw_response}")
            raise RuntimeError(raw_response)

        if not raw_response:
            logger.warning("Empty response from LLM")
            raise RuntimeError("LLM returned empty response")

        try:
            cleaned_response = self._clean_json_string(raw_response)
            data = json.loads(cleaned_response)
            
            # Fill missing fields for response model
            if "genre" not in data: data["genre"] = track.genre or "Unknown"
            if "subgenre" not in data: data["subgenre"] = track.subgenre or ""
            
            data = self._normalize_analysis_data(track, data, mode)
            response = GenreAnalysisResponse(**data)
            
            current_genre = track.genre or "Unknown"
            should_update = overwrite or current_genre.lower() == "unknown"
            
            if should_update:
                if mode in [AnalysisMode.GENRE, AnalysisMode.BOTH]:
                    track.genre = response.genre
                if mode in [AnalysisMode.SUBGENRE, AnalysisMode.BOTH]:
                    track.subgenre = response.subgenre
                
                track.is_genre_verified = True
                self.session.commit()
                self.session.refresh(track)
                
            return response
        except Exception as e:
            logger.error(f"LLM JSON Parse Error: {e}, Raw: {raw_response}")
            raise RuntimeError(f"Failed to parse LLM response: {str(e)}")

    def analyze_tracks_batch_with_llm(self, track_ids: List[int], mode: AnalysisMode = AnalysisMode.BOTH) -> List[GenreUpdateResult]:
        if not track_ids:
            return []

        tracks = self.repository.get_tracks_by_ids(track_ids)
        if not tracks:
            return []

        track_lines = []
        for t in tracks:
            safe_title = (t.title or "").replace("|", " ")
            safe_artist = (t.artist or "").replace("|", " ")
            bpm_str = f"{int(t.bpm)}" if t.bpm and t.bpm > 0 else ""
            
            # Minimal Input: ID|Title|Artist|BPM
            features = [str(t.id), safe_title, safe_artist, bpm_str]
            track_lines.append("|".join(features))
        
        input_text = "\n".join(track_lines)

        prompt = f"""
        Analyze tracks to determine {mode.value} for a DJ music library.
        Input: ID|Title|Artist|BPM
        {input_text}

        {DJ_GENRE_GUIDE}

        Output Format:
        """
        
        if mode == AnalysisMode.GENRE:
            prompt += "ID|Genre"
        elif mode == AnalysisMode.SUBGENRE:
            prompt += "ID|Subgenre"
        else:
            prompt += "ID|Genre|Subgenre"

        prompt += """
        
        Rules:
        - One line per track.
        - Standard DJ library genres only.
        - Output only ONE single genre/subgenre per column. Do NOT use slashes (/) or commas (,).
        - If multiple genres apply, choose the most dominant one.
        - No markdown/header.
        """

        raw_response = generate_text(self.session, prompt)
        
        if is_llm_error(raw_response):
            logger.error(f"Batch Analysis Failed: {raw_response}")
            raise RuntimeError(raw_response)
        if not raw_response.strip():
            logger.error("Batch Analysis Failed: empty response from LLM")
            raise RuntimeError("LLM returned empty response")

        new_genres_map = {}
        lines = raw_response.strip().split('\n')
        
        for line in lines:
            line = line.strip()
            if not line: continue
            parts = line.split('|')
            
            try:
                t_id_str = parts[0].strip()
                t_id_match = re.search(r'\d+', t_id_str)
                if not t_id_match: continue
                track_id = int(t_id_match.group(0))
                
                if mode == AnalysisMode.GENRE and len(parts) >= 2:
                    new_genres_map[track_id] = {"genre": parts[1].strip()}
                elif mode == AnalysisMode.SUBGENRE and len(parts) >= 2:
                    new_genres_map[track_id] = {"subgenre": parts[1].strip()}
                elif mode == AnalysisMode.BOTH and len(parts) >= 3:
                    new_genres_map[track_id] = {"genre": parts[1].strip(), "subgenre": parts[2].strip()}
            except Exception as e:
                continue

        if not new_genres_map:
            logger.error(f"Batch Analysis Failed: no parseable rows. Raw: {raw_response}")
            raise RuntimeError("Failed to parse LLM response: no parseable rows")
        
        updated_results = []
        
        for track in tracks:
            updates = new_genres_map.get(track.id)
            if not updates:
                continue
            
            old_genre = track.genre or "Unknown"
            has_changes = False
            updates = self._normalize_analysis_data(track, updates, mode)
            
            if "genre" in updates:
                new_g = re.sub(r'^[\"\']|[\"\']$', '', updates["genre"])
                if new_g and new_g.lower() != "unknown" and track.genre != new_g:
                    track.genre = new_g
                    has_changes = True
            
            if "subgenre" in updates:
                new_s = re.sub(r'^[\"\']|[\"\']$', '', updates["subgenre"])
                if track.subgenre != new_s:
                    track.subgenre = new_s
                    has_changes = True

            if has_changes:
                updated_results.append(GenreUpdateResult(
                    track_id=track.id,
                    title=track.title,
                    artist=track.artist,
                    old_genre=old_genre,
                    new_genre=track.genre # Return the new main genre for display
                ))
            
            track.is_genre_verified = True
            # SQLModelは変更を自動追跡するため、session.add()は不要
        
        self.session.commit()
        logger.info(f"Batch analyzed {len(tracks)} tracks. Updated {len(updated_results)} tracks.")
        
        return updated_results

    def _clean_json_string(self, text: str) -> str:
        text = text.strip()
        if text.startswith("```json"):
            text = text[7:]
        elif text.startswith("```"):
            text = text[3:]
        
        if text.endswith("```"):
            text = text[:-3]
            
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1:
            text = text[start:end+1]
            
        return text.strip()

    def _normalize_analysis_data(self, track: Track, data: Dict[str, Any], mode: AnalysisMode) -> Dict[str, Any]:
        normalized = dict(data)

        if "genre" in normalized:
            normalized["genre"] = self._normalize_genre_label(str(normalized["genre"]))
        if "subgenre" in normalized:
            normalized["subgenre"] = self._normalize_subgenre_label(str(normalized["subgenre"]))

        if mode in [AnalysisMode.GENRE, AnalysisMode.BOTH]:
            normalized["genre"] = normalized.get("genre", track.genre or "Unknown")
        if mode in [AnalysisMode.SUBGENRE, AnalysisMode.BOTH]:
            normalized["subgenre"] = normalized.get("subgenre", track.subgenre or "")

        normalized.setdefault("reason", "Classified from title, artist, BPM, and DJ taxonomy.")
        normalized.setdefault("confidence", "Medium")
        return normalized

    def _normalize_genre_label(self, value: str) -> str:
        label = self._sanitize_label(value)
        if not label:
            return "Unknown"
        return GENRE_ALIASES.get(label.lower(), label)

    def _normalize_subgenre_label(self, value: str) -> str:
        label = self._sanitize_label(value)
        if not label:
            return ""
        return SUBGENRE_ALIASES.get(label.lower(), label)

    def _sanitize_label(self, value: str) -> str:
        label = re.sub(r'^[\"\']|[\"\']$', '', value or "").strip()
        label = re.sub(r'\s+', ' ', label)
        if "/" in label:
            label = label.split("/")[0].strip()
        if "," in label:
            label = label.split(",")[0].strip()
        return label

    def batch_update_genres(self, request: GenreBatchUpdateRequest) -> Dict[str, Any]:
        parent_track = self.track_repository.get_by_id(request.parent_track_id)
        if not parent_track:
            raise ValueError("Parent track not found")
            
        if not parent_track.genre:
            raise ValueError("Parent track has no genre")
            
        targets = self.repository.get_tracks_by_ids(request.target_track_ids)
        
        updated_count = 0
        for track in targets:
            track.genre = parent_track.genre
            track.subgenre = parent_track.subgenre
            track.is_genre_verified = True
            # SQLModelは変更を自動追跡するため、session.add()は不要
            updated_count += 1
            
        self.session.commit()
        
        return {"updated_count": updated_count, "genre": parent_track.genre}

    def execute_cleanup(self, target_genre: str, track_ids: List[int], mode: AnalysisMode = AnalysisMode.GENRE) -> Dict[str, Any]:
        targets = self.repository.get_tracks_by_ids(track_ids)
        
        updated_count = 0
        for track in targets:
            if mode == AnalysisMode.SUBGENRE:
                track.subgenre = target_genre
            else:
                track.genre = target_genre
            
            track.is_genre_verified = True
            # SQLModelは変更を自動追跡するため、session.add()は不要
            updated_count += 1
            
        self.session.commit()
        return {"updated_count": updated_count, "genre": target_genre}

    def get_cleanup_suggestions(self, mode: AnalysisMode = AnalysisMode.GENRE) -> List[GenreCleanupGroup]:
        tracks = self.repository.get_all_tracks_with_genre()
        
        groups = defaultdict(lambda: defaultdict(list))
        
        def normalize_genre(g: str) -> str:
            s = g.lower()
            for pattern, replacement in GENRE_ABBREVIATIONS:
                s = re.sub(pattern, replacement, s)
            s = s.replace('&', ' and ')
            tokens = re.split(GENRE_SEPARATORS_REGEX, s)
            tokens = [t for t in tokens if t]
            tokens.sort()
            return "".join(tokens)

        for t in tracks:
            raw_value = t.subgenre if mode == AnalysisMode.SUBGENRE else t.genre
            if not raw_value: continue

            norm = normalize_genre(raw_value)
            if not norm: continue
            groups[norm][raw_value].append(t)
            
        cleanup_candidates = []
        
        for norm_key, variants in groups.items():
            if len(variants) < 2:
                continue
            
            sorted_variants = sorted(
                variants.keys(), 
                key=lambda k: (
                    0 if '&' in k else 1,
                    1 if re.search(r'\band\b', k.lower()) else 0,
                    -len(variants[k]),
                    len(k),
                    k
                )
            )
            primary_genre = sorted_variants[0]
            
            all_suggestions = []
            variant_names = []
            
            for genre_name, track_list in variants.items():
                variant_names.append(genre_name)
                if genre_name != primary_genre:
                    for t in track_list:
                        all_suggestions.append(TrackSuggestion(
                            id=t.id,
                            title=t.title,
                            artist=t.artist,
                            bpm=t.bpm,
                            filepath=t.filepath,
                            current_genre=t.genre
                        ))
            
            if all_suggestions:
                cleanup_candidates.append(GenreCleanupGroup(
                    primary_genre=primary_genre,
                    variant_genres=variant_names,
                    track_count=len(all_suggestions),
                    suggestions=all_suggestions
                ))
                
        cleanup_candidates.sort(key=lambda x: x.track_count, reverse=True)
        
        return cleanup_candidates

    def apply_genres_to_files(self, track_ids: List[int]) -> Dict[str, int]:
        success_count = 0
        fail_count = 0
        
        if not track_ids:
            # Fetch all tracks if no IDs provided
            # Using a large limit or iterating if possible. 
            # For now, let's use repository.find_all with a large limit or add get_all
            # Assuming find_all takes limit.
            tracks = self.track_repository.find_all(limit=10000) 
        else:
            tracks = []
            for tid in track_ids:
                t = self.track_repository.get_by_id(tid)
                if t:
                    tracks.append(t)
        
        for track in tracks:
            if not track.filepath:
                fail_count += 1
                continue
            
            # Fetch lyrics
            lyrics_content = None
            lyrics = self.session.get(Lyrics, track.id)
            if lyrics:
                lyrics_content = lyrics.content
                
            if update_file_tags_extended(
                track.filepath,
                title=track.title,
                artist=track.artist,
                album=track.album,
                year=track.year,
                genre=track.genre,
                lyrics=lyrics_content
            ):
                success_count += 1
            else:
                fail_count += 1
                
        return {"success": success_count, "failed": fail_count}
