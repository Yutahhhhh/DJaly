from typing import List, Tuple, Optional, Dict, Any
from sqlmodel import Session, select, text
from domain.models.track import Track, TrackEmbedding
import numpy as np
import json
from utils.genres import genre_expander

class RecommendationRepository:
    def __init__(self, session: Session):
        self.session = session

    def _parse_embedding(self, embedding_json: Optional[str]) -> Optional[np.ndarray]:
        if not embedding_json:
            return None
        try:
            vec = np.array(json.loads(embedding_json))
            return vec if vec.size > 0 else None
        except:
            return None

    def get_candidate_vectors(self) -> np.ndarray:
        stmt = select(TrackEmbedding.embedding_json).join(Track).where(Track.is_genre_verified == False)
        candidates = self.session.exec(stmt).all()
        vectors = [self._parse_embedding(emb) for emb in candidates]
        vectors = [v for v in vectors if v is not None]
        return np.array(vectors) if vectors else np.array([])

    def get_candidates_with_ids(self) -> Tuple[List[int], np.ndarray]:
        stmt = select(Track.id, TrackEmbedding.embedding_json).join(TrackEmbedding).where(Track.is_genre_verified == False)
        results = self.session.exec(stmt).all()
        ids = []
        vectors = []
        for tid, emb in results:
            vec = self._parse_embedding(emb)
            if vec is not None:
                ids.append(tid)
                vectors.append(vec)
        return ids, np.array(vectors) if vectors else np.array([])

    def get_parent_vectors(self) -> List[Tuple[int, np.ndarray]]:
        stmt = select(Track.id, TrackEmbedding.embedding_json).join(TrackEmbedding).where(Track.is_genre_verified == True)
        results = self.session.exec(stmt).all()
        parents = []
        for tid, emb in results:
            vec = self._parse_embedding(emb)
            if vec is not None:
                parents.append((tid, vec))
        return parents

    def get_verified_tracks_with_embeddings(self, exclude_track_id: int = None) -> List[Tuple[str, np.ndarray]]:
        query = select(Track.genre, TrackEmbedding.embedding_json).join(TrackEmbedding).where(Track.is_genre_verified == True)
        if exclude_track_id:
            query = query.where(Track.id != exclude_track_id)
        
        results = self.session.exec(query).all()
        data = []
        for genre, emb_json in results:
            if not genre: continue
            vec = self._parse_embedding(emb_json)
            if vec is not None:
                data.append((genre, vec))
        return data

    def get_track_embedding(self, track_id: int) -> Optional[np.ndarray]:
        emb = self.session.get(TrackEmbedding, track_id)
        return self._parse_embedding(emb.embedding_json) if emb else None

    def get_tracks_by_ids(self, track_ids: List[int]) -> Dict[int, Track]:
        if not track_ids:
            return {}
        stmt = select(Track).where(Track.id.in_(track_ids))
        tracks = self.session.exec(stmt).all()
        return {t.id: t for t in tracks}

    def fetch_candidates_pool(
        self,
        vibe_params: Dict[str, Any],
        genres: Optional[List[str]] = None,
        limit: int = 200,
        exclude_ids: List[int] = None
    ) -> List[Dict[str, Any]]:
        """
        指定されたVibe(特徴量)とジャンルに基づき、DuckDBから候補プールのトラックを取得する。
        """
        
        # 1. Base Query Construction
        # Vector検索のためにTrackEmbeddingをJOIN
        query_str = """
            SELECT 
                t.id, t.title, t.artist, t.bpm, t.key, t.genre,
                t.duration, t.album, t.filepath,
                t.energy, t.danceability, t.brightness, t.loudness,
                te.embedding_json
            FROM tracks t
            LEFT JOIN track_embeddings te ON t.id = te.track_id
            WHERE 1=1
        """
        params = {}
        
        # 2. Filtering Logic
        if exclude_ids:
            query_str += " AND t.id NOT IN :exclude_ids"
            params["exclude_ids"] = tuple(exclude_ids)

        if genres:
            # ★ AIによる動的ジャンル拡張 (ここでキャッシュまたはLLMを使用)
            expanded_genres_set = set()
            for g in genres:
                subs = genre_expander.expand(self.session, g)
                for s in subs:
                    expanded_genres_set.add(s)
            
            for g in genres:
                expanded_genres_set.add(g)

            if expanded_genres_set:
                query_str += " AND t.genre IN :genres"
                params["genres"] = tuple(expanded_genres_set)
            
        # BPM Filter
        if "bpm" in vibe_params and vibe_params["bpm"] > 0:
            target_bpm = vibe_params["bpm"]
            query_str += " AND (t.bpm BETWEEN :min_bpm AND :max_bpm OR t.bpm = 0 OR t.bpm IS NULL)"
            params["min_bpm"] = target_bpm * 0.6
            params["max_bpm"] = target_bpm * 1.4

        # 3. Scoring Logic in SQL
        order_clauses = []
        
        if "energy" in vibe_params:
            query_str += " AND t.energy BETWEEN :min_energy AND :max_energy"
            params["min_energy"] = max(0, vibe_params["energy"] - 0.3)
            params["max_energy"] = min(1, vibe_params["energy"] + 0.3)
            order_clauses.append(f"ABS(t.energy - {vibe_params['energy']})")

        if "danceability" in vibe_params:
            order_clauses.append(f"ABS(t.danceability - {vibe_params['danceability']})")

        if "brightness" in vibe_params:
            order_clauses.append(f"ABS(t.brightness - {vibe_params['brightness']})")

        if "noisiness" in vibe_params:
            order_clauses.append(f"ABS(t.noisiness - {vibe_params['noisiness']})")

        if order_clauses:
            query_str += " ORDER BY (" + " + ".join(order_clauses) + ") ASC"
        else:
            query_str += " ORDER BY t.created_at DESC"
            
        query_str += f" LIMIT {limit}"

        results = self.session.connection().execute(text(query_str), params).fetchall()
        
        candidates = []
        for row in results:
            vec = None
            if row.embedding_json:
                try:
                    vec = np.array(json.loads(row.embedding_json))
                except: pass
            
            candidates.append({
                "id": row.id,
                "track": Track(
                    id=row.id, title=row.title, artist=row.artist, bpm=row.bpm, key=row.key, genre=row.genre,
                    duration=row.duration, album=row.album, filepath=row.filepath,
                    energy=row.energy, danceability=row.danceability, brightness=row.brightness, loudness=row.loudness,
                ),
                "vector": vec
            })
            
        return candidates
