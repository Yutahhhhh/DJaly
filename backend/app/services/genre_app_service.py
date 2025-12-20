from typing import List, Optional, Dict, Any
from sqlmodel import Session
import json
import re
from collections import defaultdict

from domain.models.track import Track
from infra.repositories.genre_repository import GenreRepository
from infra.repositories.track_repository import TrackRepository
from api.schemas.genres import (
    GenreAnalysisResponse, 
    GenreBatchUpdateRequest, 
    GenreCleanupGroup, 
    TrackSuggestion,
    GenreUpdateResult
)
from utils.llm import generate_text
from utils.metadata import update_file_genre
from utils.logger import get_logger
from domain.constants import GENRE_ABBREVIATIONS, GENRE_SEPARATORS_REGEX

logger = get_logger(__name__)

class GenreAppService:
    def __init__(self, session: Session):
        self.session = session
        self.repository = GenreRepository(session)
        self.track_repository = TrackRepository(session)

    def get_unknown_tracks(self, offset: int = 0, limit: int = 50) -> List[Track]:
        return self.repository.get_unknown_tracks(offset, limit)

    def get_all_unknown_track_ids(self) -> List[int]:
        return self.repository.get_all_unknown_track_ids()

    def get_all_genres(self) -> List[str]:
        return self.repository.get_all_unique_genres()

    def analyze_track_with_llm(self, track_id: int, overwrite: bool = False) -> GenreAnalysisResponse:
        track = self.track_repository.get_by_id(track_id)
        if not track:
            raise ValueError("Track not found")
        
        prompt = f"""
        Analyze the following music track metadata and suggest a precise music genre.
        
        Metadata:
        - Title: {track.title}
        - Artist: {track.artist}
        - Album: {track.album}
        
        Audio Features (Already Analyzed):
        - BPM: {int(track.bpm) if track.bpm else "Unknown"}
        - Key: {track.key}
        - Scale: {track.scale}
        - Energy: {track.energy:.2f}
        - Danceability: {track.danceability:.2f}
        - Loudness: {track.loudness:.2f}
        - Brightness: {track.brightness:.2f}
        - Noisiness: {track.noisiness:.2f}
        - Contrast: {track.contrast:.2f}
        - Loudness Range: {track.loudness_range:.2f}
        - Spectral Flux: {track.spectral_flux:.2f}
        - Spectral Rolloff: {track.spectral_rolloff:.2f}
        
        INSTRUCTIONS:
        1. Rely primarily on the Artist and Title to determine the genre.
        2. PRESERVE SPECIFICITY: Do NOT generalize distinct styles into broad categories. If a track belongs to a specific sub-genre or regional style, use that specific name instead of the parent genre.
        3. DJ TOOLS: Ignore keywords like "Transition", "Intro", "Clean", "Dirty", or BPM ranges in titles. Focus on the original song's style.
        4. POP vs HOUSE: Do not classify mainstream Pop artists as "Deep House" unless it is explicitly a Remix.
        5. Use BPM and other audio features to validate the sub-genre.
        6. Be specific (e.g. "Deep House" instead of just "House").
        7. Use only standard, industry-recognized genre names. Do not invent new genre names.
        8. Output exactly ONE genre. If multiple fit, choose the most dominant one. Do not use slashes or commas.
        
        Return the result in JSON format with the following keys:
        - "genre": The suggested genre name.
        - "reason": A short explanation of why this genre was chosen (max 1 sentence).
        - "confidence": "High", "Medium", or "Low".
        
        Output ONLY the JSON string.
        """
        
        raw_response = generate_text(self.session, prompt)
        
        if raw_response.startswith("API_ERROR:") or raw_response.startswith("CONNECTION_ERROR:") or raw_response.startswith("BLOCKED:"):
            logger.error(f"Single Analysis Failed: {raw_response}")
            raise RuntimeError(raw_response)

        if not raw_response:
            logger.warning("Empty response from LLM")
            raise RuntimeError("LLM returned empty response")

        try:
            cleaned_response = self._clean_json_string(raw_response)
            data = json.loads(cleaned_response)
            response = GenreAnalysisResponse(**data)
            
            current_genre = track.genre or "Unknown"
            if overwrite or current_genre.lower() == "unknown":
                track.genre = response.genre
                track.is_genre_verified = True
                self.session.add(track)
                self.session.commit()
                self.session.refresh(track)
                
            return response
        except Exception as e:
            logger.error(f"LLM JSON Parse Error: {e}, Raw: {raw_response}")
            raise RuntimeError(f"Failed to parse LLM response: {str(e)}")

    def analyze_tracks_batch_with_llm(self, track_ids: List[int]) -> List[GenreUpdateResult]:
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
            def safe_float(val):
                return f"{val:.2f}" if val is not None else "0.00"

            features = [
                str(t.id), safe_title, safe_artist, bpm_str, 
                t.key or "", t.scale or "",
                safe_float(t.energy), safe_float(t.danceability), safe_float(t.loudness),
                safe_float(t.brightness), safe_float(t.noisiness), safe_float(t.contrast)
            ]
            track_lines.append("|".join(features))
        
        input_text = "\n".join(track_lines)

        prompt = f"""
        Analyze the metadata and audio features to determine the precise music genre for each track.
        
        Input Format: ID|Title|Artist|BPM|Key|Scale|Energy|Danceability|Loudness|Brightness|Noisiness|Contrast
        {input_text}

        INSTRUCTIONS:
        - Provide the most specific sub-genre possible based on the audio features and metadata.
        - PRESERVE SPECIFICITY: Do NOT generalize distinct styles into broad categories. If a track belongs to a specific sub-genre or regional style, use that specific name instead of the parent genre.
        - DJ TOOLS: Ignore keywords like "Transition", "Intro", "Clean", "Dirty", or BPM ranges in titles. Classify based on the original track's style.
        - POP vs HOUSE: Do not classify mainstream Pop artists as "Deep House" unless it is explicitly a Remix.
        - Pay close attention to BPM. Ensure the suggested genre is consistent with the track's tempo.
        - Use only standard, industry-recognized genre names (e.g. as found on Beatport, Spotify, or Apple Music). Do not invent new genre names.
        - Avoid broad categories like "Pop", "Rock", or "Electronic" unless no specific sub-genre fits.
        - Output exactly ONE genre per track. If multiple fit, choose the most dominant one. Do not use slashes or commas.
        - CRITICAL: Output ONLY the list of "ID|Genre". Do NOT include any introduction, explanation, reasoning, or markdown formatting. Start directly with the first ID.

        Output Format: ID|Genre
        - One line per track.
        - No markdown, no header, no extra text.
        """

        raw_response = generate_text(self.session, prompt)
        
        if raw_response.startswith("API_ERROR:") or raw_response.startswith("CONNECTION_ERROR:") or raw_response.startswith("BLOCKED:"):
            logger.error(f"Batch Analysis Failed: {raw_response}")
            raise RuntimeError(raw_response)

        new_genres_map = {}
        lines = raw_response.strip().split('\n')
        
        for line in lines:
            line = line.strip()
            if not line: continue
            parts = line.split('|')
            if len(parts) >= 2:
                try:
                    t_id_str = parts[0].strip()
                    t_id_match = re.search(r'\d+', t_id_str)
                    if not t_id_match: continue
                    
                    track_id = int(t_id_match.group(0))
                    genre = parts[1].strip()
                    genre = re.sub(r'^[\"\']|[\"\']$', '', genre)
                    
                    if genre and genre.lower() != "unknown":
                        new_genres_map[track_id] = genre
                except Exception as e:
                    logger.warning(f"Failed to parse line: {line} - {e}")
                    continue
        
        if not new_genres_map and raw_response:
            logger.error(f"No valid lines parsed from response. Raw: {raw_response}")
            
        updated_results = []
        
        for track in tracks:
            new_genre = new_genres_map.get(track.id)
            if not new_genre:
                continue
                
            old_genre = track.genre or "Unknown"
            
            if old_genre != new_genre:
                track.genre = new_genre
                updated_results.append(GenreUpdateResult(
                    track_id=track.id,
                    title=track.title,
                    artist=track.artist,
                    old_genre=old_genre,
                    new_genre=new_genre
                ))
            
            track.is_genre_verified = True
            self.session.add(track)
        
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
            track.is_genre_verified = True
            self.session.add(track)
            updated_count += 1
            
        self.session.commit()
        
        return {"updated_count": updated_count, "genre": parent_track.genre}

    def execute_cleanup(self, target_genre: str, track_ids: List[int]) -> Dict[str, Any]:
        targets = self.repository.get_tracks_by_ids(track_ids)
        
        updated_count = 0
        for track in targets:
            track.genre = target_genre
            track.is_genre_verified = True 
            self.session.add(track)
            updated_count += 1
            
        self.session.commit()
        return {"updated_count": updated_count, "genre": target_genre}

    def get_cleanup_suggestions(self) -> List[GenreCleanupGroup]:
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
            norm = normalize_genre(t.genre)
            if not norm: continue
            groups[norm][t.genre].append(t)
            
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
            tracks = self.repository.get_all_tracks_with_genre_any()
        else:
            tracks = []
            for tid in track_ids:
                t = self.track_repository.get_by_id(tid)
                if t:
                    tracks.append(t)
        
        for track in tracks:
            if not track.genre or not track.filepath:
                fail_count += 1
                continue
                
            if update_file_genre(track.filepath, track.genre):
                success_count += 1
            else:
                fail_count += 1
                
        return {"success": success_count, "failed": fail_count}
