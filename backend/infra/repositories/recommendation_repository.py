from typing import List, Tuple, Optional, Dict, Any
from sqlmodel import Session, select, text
from domain.models.track import Track, TrackEmbedding
from domain.models.lyrics import Lyrics
from utils.embedding import LEGACY_MODELS, embedding_space
import numpy as np
import json
import math

class RecommendationRepository:
    def __init__(self, session: Session):
        self.session = session

    def _parse_embedding(self, embedding_json: Optional[str]) -> Optional[np.ndarray]:
        if not embedding_json:
            return None
        try:
            vec = np.array(json.loads(embedding_json), dtype=float)
            return vec if vec.ndim == 1 and vec.size > 0 and np.isfinite(vec).all() else None
        except:
            return None

    @staticmethod
    def _model_condition(model_name):
        if embedding_space(model_name) == "musicnn":
            return TrackEmbedding.model_name.in_(LEGACY_MODELS) | (TrackEmbedding.model_name == None)
        return TrackEmbedding.model_name == model_name

    def get_embedding_model(self, track_id: int) -> str:
        emb = self.session.get(TrackEmbedding, track_id)
        return embedding_space(emb.model_name if emb else None)

    def get_candidate_vectors(self, mode: str = "genre", model_name=None) -> np.ndarray:
        query = select(TrackEmbedding.embedding_json).join(Track)
        if model_name is not None:
            query = query.where(self._model_condition(model_name))
        if mode == "subgenre":
            query = query.where((Track.subgenre == None) | (Track.subgenre == ""))
        else:
            query = query.where(Track.is_genre_verified == False)
            
        candidates = self.session.exec(query).all()
        vectors = [self._parse_embedding(emb) for emb in candidates]
        vectors = [v for v in vectors if v is not None]
        return np.array(vectors) if vectors else np.array([])

    def get_candidates_with_ids(self, mode: str = "genre", model_name=None) -> Tuple[List[int], np.ndarray]:
        query = select(Track.id, TrackEmbedding.embedding_json).join(TrackEmbedding)
        if model_name is not None:
            query = query.where(self._model_condition(model_name))
        if mode == "subgenre":
            query = query.where((Track.subgenre == None) | (Track.subgenre == ""))
        else:
            query = query.where(Track.is_genre_verified == False)
            
        results = self.session.exec(query).all()
        ids = []
        vectors = []
        for tid, emb in results:
            vec = self._parse_embedding(emb)
            if vec is not None:
                ids.append(tid)
                vectors.append(vec)
        return ids, np.array(vectors) if vectors else np.array([])

    def get_parent_vectors(self) -> List[Tuple[int, np.ndarray]]:
        stmt = select(Track.id, TrackEmbedding.embedding_json, TrackEmbedding.model_name).join(TrackEmbedding).where(Track.is_genre_verified == True)
        results = self.session.exec(stmt).all()
        parents = []
        for tid, emb, model in results:
            vec = self._parse_embedding(emb)
            if vec is not None:
                parents.append((tid, vec, embedding_space(model)))
        return parents

    def get_verified_tracks_with_embeddings(self, exclude_track_id: int = None, model_name=None) -> List[Tuple[str, np.ndarray]]:
        query = select(Track.genre, TrackEmbedding.embedding_json).join(TrackEmbedding).where(Track.is_genre_verified == True)
        if model_name is not None:
            query = query.where(self._model_condition(model_name))
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

    @staticmethod
    def _to_float(value) -> Optional[float]:
        if isinstance(value, bool):
            return None
        try:
            number = float(value)
            return number if math.isfinite(number) else None
        except (TypeError, ValueError):
            return None

    def fetch_candidates_pool(
        self,
        target_params: Dict[str, Any],
        genres: Optional[List[str]] = None,
        subgenres: Optional[List[str]] = None,
        limit: int = 200,
        exclude_ids: List[int] = None,
        candidate_ids: Optional[List[int]] = None,
    ) -> List[Dict[str, Any]]:
        """
        指定された構造化ターゲットとジャンルに基づき、歌詞情報とリリース年を含めて候補を取得
        """
        query_str = """
            SELECT
                t.id, t.title, t.artist, t.bpm, t.key, t.genre, t.subgenre,
                t.duration, t.album, t.filepath, t.year,
                t.energy, t.danceability, t.brightness, t.loudness, t.contrast, t.noisiness,
                te.embedding_json, te.model_name,
                (l.content IS NOT NULL AND length(trim(l.content)) > 0) as db_has_lyrics
            FROM tracks t
            LEFT JOIN track_embeddings te ON t.id = te.track_id
            LEFT JOIN lyrics l ON t.id = l.track_id
            WHERE 1=1
        """
        params = {}
        order_clauses = []

        if candidate_ids is not None:
            if not candidate_ids:
                return []
            query_str += " AND t.id IN :candidate_ids"
            params["candidate_ids"] = tuple(candidate_ids)

        if exclude_ids:
            query_str += " AND t.id NOT IN :exclude_ids"
            params["exclude_ids"] = tuple(exclude_ids)

        genre_conditions = []
        if genres:
            genre_conditions.append("t.genre IN :genres")
            params["genres"] = tuple(genres)
        if subgenres:
            genre_conditions.append("t.subgenre IN :subgenres")
            params["subgenres"] = tuple(subgenres)
        if genre_conditions:
            query_str += " AND (" + " OR ".join(genre_conditions) + ")"

        target_bpm = self._to_float(target_params.get("bpm"))
        if target_bpm is not None and target_bpm > 0:
            # Use the same half/double-time interpretations as the transition scorer.
            tempo_distance = """CASE WHEN t.bpm > 0 AND isfinite(t.bpm) THEN LEAST(
                ABS(LOG2(t.bpm / :target_bpm)),
                ABS(LOG2(t.bpm / :target_bpm) - 1),
                ABS(LOG2(t.bpm / :target_bpm) + 1)
            ) ELSE 1000 END"""
            params["target_bpm"] = target_bpm
            params["max_tempo_distance"] = math.log2(1.4)
            query_str += f" AND (({tempo_distance}) <= :max_tempo_distance OR t.bpm = 0 OR t.bpm IS NULL)"
            order_clauses.append(tempo_distance)

        for name, operator in (("year_min", ">="), ("year_max", "<=")):
            year = self._to_float(target_params.get(name))
            if year is not None:
                query_str += f" AND t.year {operator} :{name}"
                params[name] = int(year)

        target_energy = self._to_float(target_params.get("energy"))
        if target_energy is not None:
            query_str += " AND t.energy BETWEEN :min_energy AND :max_energy"
            params["min_energy"] = max(0.0, target_energy - 0.4)
            params["max_energy"] = min(1.0, target_energy + 0.4)
            order_clauses.append("ABS(t.energy - :order_energy)")
            params["order_energy"] = target_energy

        for feature in ("danceability", "brightness", "noisiness"):
            target = self._to_float(target_params.get(feature))
            if target is not None:
                order_clauses.append(f"COALESCE(ABS(t.{feature} - :order_{feature}), 1.0)")
                params[f"order_{feature}"] = target

        if order_clauses:
            query_str += " ORDER BY (" + " + ".join(order_clauses) + ") ASC, t.id ASC"
        else:
            query_str += " ORDER BY t.created_at DESC, t.id ASC"

        query_str += " LIMIT :pool_limit"
        params["pool_limit"] = int(limit)

        results = self.session.connection().execute(text(query_str), params).fetchall()
        
        candidates = []
        for row in results:
            vec = self._parse_embedding(row.embedding_json)
            has_ly = bool(row.db_has_lyrics)
            
            track_obj = Track(
                id=row.id, title=row.title, artist=row.artist, bpm=row.bpm, key=row.key, 
                genre=row.genre, subgenre=row.subgenre or "", duration=row.duration, 
                album=row.album or "", filepath=row.filepath, year=row.year,
                energy=row.energy, danceability=row.danceability, brightness=row.brightness, 
                loudness=row.loudness, contrast=row.contrast, noisiness=row.noisiness,
                has_lyrics=has_ly # オブジェクトに直接セット
            )
            
            candidates.append({
                "id": row.id,
                "track": track_obj,
                "vector": vec,
                "embedding_model": row.model_name,
                "has_lyrics": has_ly # 辞書側にもセット（サービス層での利用を確実に）
            })
            
        return candidates
