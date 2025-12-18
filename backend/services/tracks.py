from typing import List, Optional, Dict, Any
from sqlmodel import Session, select, or_, and_, col, text
from sqlalchemy.orm import defer
import json
import time

from models import Track, TrackEmbedding
from utils.llm import generate_vibe_parameters
from db import get_setting_value

class TrackService:
    def update_genre(self, session: Session, track_id: int, genre: str) -> Optional[Track]:
        track = session.get(Track, track_id)
        if not track:
            return None
        
        track.genre = genre
        track.is_genre_verified = True
        session.add(track)
        session.commit()
        session.refresh(track)
        return track

    def get_similar_tracks(self, session: Session, track_id: int, limit: int = 20) -> List[Track]:
        """
        Vector Search: Find tracks similar to the given track_id using embeddings.
        """
        # 1. Get target embedding
        target_embedding = session.exec(
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
            
            results = session.exec(query).all()
            return results

        except Exception as e:
            print(f"Vector search error: {e}")
            raise e

    def get_tracks(
        self,
        session: Session,
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
        start_time = time.time()
        print(f"DEBUG: Start get_tracks")

        query = select(Track)
        
        # Vibe Search Logic (Sort by similarity to inferred features)
        if vibe_prompt:
            # LLM Model setting
            model_name = get_setting_value(session, "llm_model") or "llama3.2"
            target_params = generate_vibe_parameters(vibe_prompt, model_name=model_name, session=session)
            
            print(f"DEBUG: Target Params: {target_params}") # Debug log

            if target_params:
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
                # Fallback if LLM fails
                query = query.order_by(Track.created_at.desc())
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
        
        query_build_time = time.time()
        print(f"DEBUG: Query built in {query_build_time - start_time:.4f}s")
        
        tracks = session.exec(query).all()
        
        query_exec_time = time.time()
        print(f"DEBUG: Query executed in {query_exec_time - query_build_time:.4f}s. Fetched {len(tracks)} tracks.")
        
        return tracks
