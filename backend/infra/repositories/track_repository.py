from typing import List, Optional, Dict, Any
from sqlmodel import Session, select, or_, and_, col, text
import json

from domain.models.track import Track, TrackEmbedding

class TrackRepository:
    def __init__(self, session: Session):
        self.session = session

    def get_by_id(self, track_id: int) -> Optional[Track]:
        return self.session.get(Track, track_id)

    def find_all(self, offset: int = 0, limit: int = 100) -> List[Track]:
        return self.session.exec(select(Track).offset(offset).limit(limit)).all()

    def update_genre(self, track_id: int, genre: str, verified: bool = True) -> Optional[Track]:
        track = self.get_by_id(track_id)
        if track:
            track.genre = genre
            track.is_genre_verified = verified
            self.session.add(track)
            self.session.commit()
            self.session.refresh(track)
        return track

    def get_similar_tracks(self, track_id: int, limit: int = 20) -> List[Track]:
        """
        Vector Search: Find tracks similar to the given track_id using embeddings.
        """
        # 1. Get target embedding
        target_embedding = self.session.exec(
            select(TrackEmbedding).where(TrackEmbedding.track_id == track_id)
        ).first()
        
        if not target_embedding:
            raise ValueError("Track embedding not found. Please analyze the track first.")

        # 2. Vector Search using DuckDB
        try:
            # Ensure the embedding is a valid JSON list
            emb_list = json.loads(target_embedding.embedding_json)
            if not emb_list:
                 raise ValueError("Empty embedding data.")
            
            # Construct the query
            query = select(Track).join(TrackEmbedding)
            query = query.where(Track.id != track_id)
            
            # DuckDB specific similarity sort
            vec_str = target_embedding.embedding_json
            
            query = query.order_by(text(f"array_cosine_similarity(CAST(track_embeddings.embedding_json AS FLOAT[200]), CAST('{vec_str}' AS FLOAT[200])) DESC"))
            query = query.limit(limit)
            
            results = self.session.exec(query).all()
            return results

        except Exception as e:
            print(f"Vector search error: {e}")
            raise e

    def search_tracks(
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
        min_year: Optional[int] = None,
        max_year: Optional[int] = None,
        target_params: Optional[Dict[str, float]] = None,
        limit: int = 100, 
        offset: int = 0
    ) -> List[Track]:
        query = select(Track)
        
        # Vibe Search Logic (Sort by similarity to inferred features)
        if target_params:
            # Extract year from target_params if not provided
            if min_year is None and "year_min" in target_params:
                min_year = int(target_params["year_min"])
            if max_year is None and "year_max" in target_params:
                max_year = int(target_params["year_max"])

            # Calculate Euclidean Distance Squared
            dist_expr = 0
            
            if "bpm" in target_params and target_params["bpm"] > 0:
                dist_expr += (Track.bpm - target_params["bpm"]) * (Track.bpm - target_params["bpm"]) * 0.0001
            
            if "energy" in target_params:
                dist_expr += (Track.energy - target_params["energy"]) * (Track.energy - target_params["energy"])
                
            if "danceability" in target_params:
                dist_expr += (Track.danceability - target_params["danceability"]) * (Track.danceability - target_params["danceability"])
                
            if "brightness" in target_params:
                dist_expr += (Track.brightness - target_params["brightness"]) * (Track.brightness - target_params["brightness"])
                
            if "noisiness" in target_params:
                dist_expr += (Track.noisiness - target_params["noisiness"]) * (Track.noisiness - target_params["noisiness"])

            # Sort by distance (ASC)
            query = query.order_by(dist_expr)
        else:
            # Default Sort
            query = query.order_by(Track.created_at.desc())
        
        # 1. Status Filter
        if status == "analyzed":
            query = query.where(Track.bpm > 0)
        elif status == "unanalyzed":
            query = query.where((Track.bpm == None) | (Track.bpm == 0))
        
        # 2. Metadata Filters
        if title:
            query = query.where(col(Track.title).ilike(f"%{title}%"))
        if artist:
            query = query.where(col(Track.artist).ilike(f"%{artist}%"))
        if album:
            query = query.where(col(Track.album).ilike(f"%{album}%"))
        if genres:
            query = query.where(col(Track.genre).in_(genres))
        
        # New: Key/Scale Filter logic
        if key and key != "":
            if key in ["Major", "Minor"]:
                # スケール検索: "C Major", "D# Major" などを "%Major" で検索
                query = query.where(col(Track.key).like(f"%{key}"))
            else:
                # 特定キー検索: 完全一致
                query = query.where(Track.key == key)
        
        # 3. BPM Search (Smart Range)
        if bpm and bpm > 0:
            targets = [bpm, bpm * 0.5, bpm * 2.0]
            bpm_conditions = []
            for t in targets:
                bpm_conditions.append(
                    and_(Track.bpm >= (t - bpm_range), Track.bpm <= (t + bpm_range))
                )
            query = query.where(or_(*bpm_conditions))
        
        # 4. Duration
        if min_duration is not None:
            query = query.where(Track.duration >= min_duration)
        if max_duration is not None:
            query = query.where(Track.duration <= max_duration)

        # 5. Year
        if min_year is not None:
            query = query.where(Track.year >= min_year)
        if max_year is not None:
            query = query.where(Track.year <= max_year)


        # 5. Advanced Audio Features
        if min_energy is not None:
            query = query.where(Track.energy >= min_energy)
        if max_energy is not None:
            query = query.where(Track.energy <= max_energy)
            
        if min_danceability is not None:
            query = query.where(Track.danceability >= min_danceability)
        if max_danceability is not None:
            query = query.where(Track.danceability <= max_danceability)

        if min_brightness is not None:
            query = query.where(Track.brightness >= min_brightness)
        if max_brightness is not None:
            query = query.where(Track.brightness <= max_brightness)
        
        query = query.offset(offset).limit(limit)
        
        return self.session.exec(query).all()
