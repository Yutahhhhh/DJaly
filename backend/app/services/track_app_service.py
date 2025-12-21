from typing import List, Optional, Dict, Any
from sqlmodel import Session

from domain.models.track import Track
from infra.repositories.track_repository import TrackRepository
from utils.llm import generate_vibe_parameters
from infra.database.connection import get_setting_value
from utils.genres import genre_expander

class TrackAppService:
    def __init__(self, session: Session):
        self.session = session
        self.repository = TrackRepository(session)

    def update_genre(self, track_id: int, genre: str) -> Optional[Track]:
        return self.repository.update_genre(track_id, genre)

    def get_similar_tracks(self, track_id: int, limit: int = 20) -> List[Track]:
        return self.repository.get_similar_tracks(track_id, limit)

    def get_tracks(
        self,
        status: str = "all",
        title: Optional[str] = None,
        artist: Optional[str] = None,
        album: Optional[str] = None,
        genres: Optional[List[str]] = None,
        key: Optional[str] = None,
        bpm: Optional[float] = None,
        bpm_range: float = 5.0,
        min_duration: Optional[float] = None,
        max_duration: Optional[float] = None,
        min_energy: Optional[float] = None,
        max_energy: Optional[float] = None,
        min_danceability: Optional[float] = None,
        max_danceability: Optional[float] = None,
        min_brightness: Optional[float] = None,
        max_brightness: Optional[float] = None,
        vibe_prompt: Optional[str] = None,
        limit: int = 100, 
        offset: int = 0
    ) -> List[Track]:
        
        target_params = None
        if vibe_prompt:
            model_name = get_setting_value(self.session, "llm_model") or "llama3.2"
            target_params = generate_vibe_parameters(vibe_prompt, model_name=model_name, session=self.session)
            
        # Genre Expansion Logic
        search_genres = genres
        if genres:
            expanded_genres = []
            for g in genres:
                if g.startswith("expand:"):
                    # 親ジャンル検索: "expand:House" -> "House" を展開
                    target_genre = g[7:] # "expand:" の長さを削除
                    sub_genres = genre_expander.expand(self.session, target_genre)
                    expanded_genres.extend(sub_genres)
                else:
                    # 通常検索: そのまま追加
                    expanded_genres.append(g)
            
            # Remove duplicates
            search_genres = list(set(expanded_genres))

        return self.repository.search_tracks(
            status=status,
            title=title,
            artist=artist,
            album=album,
            genres=search_genres,
            key=key,
            bpm=bpm,
            bpm_range=bpm_range,
            min_duration=min_duration,
            max_duration=max_duration,
            min_energy=min_energy,
            max_energy=max_energy,
            min_danceability=min_danceability,
            max_danceability=max_danceability,
            min_brightness=min_brightness,
            max_brightness=max_brightness,
            target_params=target_params,
            limit=limit,
            offset=offset
        )
