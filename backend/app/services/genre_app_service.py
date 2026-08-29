from typing import List, Optional, Dict, Any
from sqlmodel import Session
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

    def get_analysis_context(
        self,
        track_ids: Optional[List[int]] = None,
        mode: AnalysisMode = AnalysisMode.BOTH,
        offset: int = 0,
        limit: int = 50,
    ) -> Dict[str, Any]:
        """Return everything the connected MCP model needs to classify tracks."""
        tracks = (
            self.repository.get_tracks_by_ids(track_ids)
            if track_ids
            else self.get_unknown_tracks(offset, limit, mode)
        )
        fields = (
            "id", "title", "artist", "album", "year", "bpm", "key",
            "energy", "danceability", "brightness", "noisiness", "genre",
            "subgenre", "is_genre_verified",
        )
        return {
            "mode": mode.value,
            "taxonomy_guide": DJ_GENRE_GUIDE,
            "rules": [
                "Use English genre labels.",
                "Choose one dominant genre and one concise subgenre when applicable.",
                "Do not include edit labels such as Intro, Clean, Dirty, or Extended.",
                "Reuse the library vocabulary when it fits; introduce a label only when needed.",
                "Use confidence High, Medium, or Low. Do not mark uncertain guesses as High.",
            ],
            "existing_genres": self.repository.get_all_genres()[:60],
            "existing_subgenres": self.repository.get_all_subgenres()[:80],
            "tracks": [
                {field: getattr(track, field, None) for field in fields}
                for track in tracks
            ],
        }

    def apply_genre_analysis(
        self,
        track_id: int,
        analysis: Dict[str, Any],
        mode: AnalysisMode = AnalysisMode.BOTH,
        overwrite: bool = False,
        commit: bool = True,
    ) -> GenreAnalysisResponse:
        """Validate and apply a classification produced by the MCP client's model."""
        track = self.track_repository.get_by_id(track_id)
        if not track:
            raise ValueError("Track not found")
        normalized = self._normalize_analysis_data(track, analysis, mode)
        confidence = str(normalized.get("confidence", "Medium")).strip().title()
        if confidence not in {"High", "Medium", "Low"}:
            confidence = "Low"
        normalized["confidence"] = confidence
        normalized["reason"] = str(
            normalized.get("reason") or "Classified by the connected MCP client."
        )[:500]
        response = GenreAnalysisResponse(**normalized)

        can_update_genre = (
            overwrite
            or not track.is_genre_verified
            or not track.genre
            or track.genre.lower() == "unknown"
        )
        can_update_subgenre = overwrite or not track.subgenre
        if mode in (AnalysisMode.GENRE, AnalysisMode.BOTH) and can_update_genre:
            track.genre = response.genre
        if mode in (AnalysisMode.SUBGENRE, AnalysisMode.BOTH) and can_update_subgenre:
            track.subgenre = response.subgenre

        applied_genre = (track.genre or "").strip().lower()
        track.is_genre_verified = bool(
            applied_genre and applied_genre != "unknown" and confidence != "Low"
        )
        self.session.add(track)
        if commit:
            self.session.commit()
            self.session.refresh(track)
        return response

    def apply_genre_analyses(
        self,
        analyses: List[Dict[str, Any]],
        mode: AnalysisMode = AnalysisMode.BOTH,
        overwrite: bool = False,
    ) -> List[GenreUpdateResult]:
        """Apply a batch of structured classifications from the MCP client."""
        results: List[GenreUpdateResult] = []
        for item in analyses:
            track_id = item.get("track_id")
            if isinstance(track_id, bool):
                continue
            try:
                track_id = int(track_id)
            except (TypeError, ValueError):
                continue
            track = self.track_repository.get_by_id(track_id)
            if not track:
                continue
            old_genre = track.genre or "Unknown"
            self.apply_genre_analysis(track_id, item, mode, overwrite, commit=False)
            results.append(GenreUpdateResult(
                track_id=track.id,
                title=track.title,
                artist=track.artist,
                old_genre=old_genre,
                new_genre=track.genre,
            ))
        self.session.commit()
        return results

    def _normalize_analysis_data(self, track: Track, data: Dict[str, Any], mode: AnalysisMode) -> Dict[str, Any]:
        normalized = dict(data)

        if normalized.get("genre") is not None:
            normalized["genre"] = self._normalize_genre_label(str(normalized["genre"]))
        else:
            normalized.pop("genre", None)
        if normalized.get("subgenre") is not None:
            normalized["subgenre"] = self._normalize_subgenre_label(str(normalized["subgenre"]))
        else:
            normalized.pop("subgenre", None)

        # The response contract always includes both fields. In single-field mode,
        # preserve the other value from the track instead of inventing one.
        normalized["genre"] = normalized.get("genre", track.genre or "Unknown")
        normalized["subgenre"] = normalized.get("subgenre", track.subgenre or "")

        normalized.setdefault("reason", "Classified from title, artist, BPM, and DJ taxonomy.")
        normalized.setdefault("confidence", "Medium")
        return normalized

    @property
    def _existing_genre_map(self) -> Dict[str, str]:
        if not hasattr(self, "_genre_map_cache"):
            self._genre_map_cache = {g.lower(): g for g in self.repository.get_all_genres()}
        return self._genre_map_cache

    @property
    def _existing_subgenre_map(self) -> Dict[str, str]:
        if not hasattr(self, "_subgenre_map_cache"):
            self._subgenre_map_cache = {s.lower(): s for s in self.repository.get_all_subgenres()}
        return self._subgenre_map_cache

    def _normalize_genre_label(self, value: str) -> str:
        label = self._sanitize_label(value)
        if not label:
            return "Unknown"
        # 既存ライブラリのジャンルと case-insensitive で一致したら既存表記を再利用 (表記揺れ防止)
        existing = self._existing_genre_map.get(label.lower())
        if existing:
            return existing
        return GENRE_ALIASES.get(label.lower(), label)

    def _normalize_subgenre_label(self, value: str) -> str:
        label = self._sanitize_label(value)
        if not label:
            return ""
        existing = self._existing_subgenre_map.get(label.lower())
        if existing:
            return existing
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
