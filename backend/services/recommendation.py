from typing import List, Optional, Dict, Tuple, Any
from sqlmodel import Session, select
from sqlalchemy import text
from models import Track, TrackEmbedding
import numpy as np
import json
import random

from utils.audio_math import normalize_key, calculate_mixability_score
from utils.genres import genre_expander

class RecommendationService:
    def _parse_embedding(self, embedding_json: Optional[str]) -> Optional[np.ndarray]:
        """Helper to parse JSON embedding to numpy array."""
        if not embedding_json:
            return None
        try:
            vec = np.array(json.loads(embedding_json))
            return vec if vec.size > 0 else None
        except:
            return None

    def _fetch_candidate_vectors(self, session: Session) -> np.ndarray:
        stmt = select(TrackEmbedding.embedding_json).join(Track).where(Track.is_genre_verified == False)
        candidates = session.exec(stmt).all()
        vectors = [self._parse_embedding(emb) for emb in candidates]
        vectors = [v for v in vectors if v is not None]
        return np.array(vectors) if vectors else np.array([])

    def _fetch_candidates_with_ids(self, session: Session) -> Tuple[List[int], np.ndarray]:
        stmt = select(Track.id, TrackEmbedding.embedding_json).join(TrackEmbedding).where(Track.is_genre_verified == False)
        results = session.exec(stmt).all()
        ids = []
        vectors = []
        for tid, emb in results:
            vec = self._parse_embedding(emb)
            if vec is not None:
                ids.append(tid)
                vectors.append(vec)
        return ids, np.array(vectors) if vectors else np.array([])

    def _fetch_parent_vectors(self, session: Session) -> List[Tuple[int, np.ndarray]]:
        stmt = select(Track.id, TrackEmbedding.embedding_json).join(TrackEmbedding).where(Track.is_genre_verified == True)
        results = session.exec(stmt).all()
        parents = []
        for tid, emb in results:
            vec = self._parse_embedding(emb)
            if vec is not None:
                parents.append((tid, vec))
        return parents

    def suggest_genre(self, session: Session, track_id: int, limit: int = 5) -> Dict[str, Optional[str]]:
        target_embedding_obj = session.get(TrackEmbedding, track_id)
        target_vec = self._parse_embedding(target_embedding_obj.embedding_json) if target_embedding_obj else None
        
        if target_vec is None:
            return {"suggested_genre": None, "reason": "no_embedding"}
            
        statement = select(Track.genre, TrackEmbedding.embedding_json).join(TrackEmbedding).where(Track.is_genre_verified == True).where(Track.id != track_id)
        results = session.exec(statement).all()
        
        if not results:
            return {"suggested_genre": None, "reason": "no_verified_tracks"}
            
        genres = []
        vectors = []
        
        for genre, emb_json in results:
            if not genre: continue
            vec = self._parse_embedding(emb_json)
            if vec is not None and vec.shape == target_vec.shape:
                genres.append(genre)
                vectors.append(vec)
                
        if not vectors:
            return {"suggested_genre": None, "reason": "no_valid_candidates"}
            
        vectors_np = np.array(vectors)
        target_norm = np.linalg.norm(target_vec)
        if target_norm == 0: 
            return {"suggested_genre": None, "reason": "zero_norm_target"}
        
        dot_products = vectors_np @ target_vec
        candidate_norms = np.linalg.norm(vectors_np, axis=1)
        candidate_norms[candidate_norms == 0] = 1e-10
        
        similarities = dot_products / (candidate_norms * target_norm)
        
        k = min(len(similarities), limit * 2)
        top_indices = np.argsort(similarities)[-k:][::-1]
        
        if len(top_indices) == 0:
            return {"suggested_genre": None, "reason": "no_candidates"}
            
        genre_scores = {}
        for i, idx in enumerate(top_indices):
            genre = genres[idx]
            score = similarities[idx]
            genre_scores[genre] = genre_scores.get(genre, 0) + score
            
        suggested_genre = max(genre_scores, key=genre_scores.get)
        return {"suggested_genre": suggested_genre, "reason": None}
    
    def get_grouped_suggestions(self, session: Session, limit: int = 10, offset: int = 0, threshold: float = 0.85, summary_only: bool = False) -> List[Dict[str, Any]]:
        parents = self._fetch_parent_vectors(session)
        if not parents:
            return []

        candidate_matrix = self._fetch_candidate_vectors(session)
        
        def fetch_tracks_for_parents(parent_ids_slice):
            if not parent_ids_slice: return {}
            t_stmt = select(Track).where(Track.id.in_(parent_ids_slice))
            t_objs = session.exec(t_stmt).all()
            return {t.id: t for t in t_objs}

        if candidate_matrix.size == 0:
            parents.sort(key=lambda x: x[0])
            sliced_parents = parents[offset : offset + limit]
            parent_ids = [p[0] for p in sliced_parents]
            track_map = fetch_tracks_for_parents(parent_ids)
            
            return [{
                "parent_track": track_map.get(pid),
                "suggestion_count": 0,
                "suggestions": []
            } for pid, _ in sliced_parents if pid in track_map]

        candidate_norms = np.linalg.norm(candidate_matrix, axis=1)
        candidate_norms[candidate_norms == 0] = 1e-10
        
        parent_stats = [] 
        
        for pid, p_vec in parents:
            parent_norm = np.linalg.norm(p_vec)
            if parent_norm == 0:
                parent_stats.append((pid, 0))
                continue
                
            dot_products = candidate_matrix @ p_vec
            similarities = dot_products / (candidate_norms * parent_norm)
            count = np.count_nonzero(similarities >= threshold)
            parent_stats.append((pid, count))
            
        parent_stats.sort(key=lambda x: (x[1], x[0]))
        
        sliced_stats = parent_stats[offset : offset + limit]
        if not sliced_stats: return []
        
        parent_ids = [x[0] for x in sliced_stats]
        track_map = fetch_tracks_for_parents(parent_ids)
        
        results = []
        for pid, count in sliced_stats:
            if pid in track_map:
                results.append({
                    "parent_track": track_map[pid],
                    "suggestion_count": count,
                    "suggestions": [] 
                })
            
        return results

    def get_suggestions_for_track(self, session: Session, track_id: int, threshold: float = 0.85) -> List[Dict[str, Any]]:
        parent_embedding = session.get(TrackEmbedding, track_id)
        parent_vec = self._parse_embedding(parent_embedding.embedding_json) if parent_embedding else None
        
        if parent_vec is None:
            return []

        candidate_ids, candidate_matrix = self._fetch_candidates_with_ids(session)
        if candidate_matrix.size == 0:
            return []

        candidate_norms = np.linalg.norm(candidate_matrix, axis=1)
        candidate_norms[candidate_norms == 0] = 1e-10
        
        parent_norm = np.linalg.norm(parent_vec)
        if parent_norm == 0: return []
        
        dot_products = candidate_matrix @ parent_vec
        similarities = dot_products / (candidate_norms * parent_norm)
        
        matched_indices = np.where(similarities >= threshold)[0]
        if len(matched_indices) == 0: return []
        
        matched_sims = similarities[matched_indices]
        sorted_indices = matched_indices[np.argsort(matched_sims)[::-1]]
        top_indices = sorted_indices[:50]
        
        top_ids = [candidate_ids[i] for i in top_indices]
        
        if not top_ids: return []
        
        tracks_stmt = select(Track).where(Track.id.in_(top_ids))
        tracks = session.exec(tracks_stmt).all()
        
        track_map = {t.id: t for t in tracks}
        suggestions = []
        
        for tid in top_ids:
            if tid in track_map:
                t = track_map[tid]
                suggestions.append({
                    "id": t.id,
                    "title": t.title,
                    "artist": t.artist,
                    "bpm": t.bpm,
                    "filepath": t.filepath
                })
            
        return suggestions

class RecommendationEngine:
    """
    DuckDBの特性を活かし、SQLレベルでの高速フィルタリングとスコアリングを行う。
    Setlist構築のために候補プールを抽出する責務を持つ。
    """
    
    def fetch_candidates_pool(
        self,
        session: Session,
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
                subs = genre_expander.expand(session, g)
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

        if order_clauses:
            query_str += " ORDER BY (" + " + ".join(order_clauses) + ") ASC"
        else:
            query_str += " ORDER BY t.created_at DESC"
            
        query_str += f" LIMIT {limit}"

        results = session.connection().execute(text(query_str), params).fetchall()
        
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

class SetlistBuilder:
    """
    候補プールから、DJ的なルール（Chain Builder）に従ってセットリストを構築する責務を持つ。
    """
    
    def __init__(self):
        self.engine = RecommendationEngine()

    def build_chain(
        self,
        pool: List[Dict[str, Any]],
        seeds: List[Dict[str, Any]],
        target_length: int,
        vibe_params: Dict[str, Any]
    ) -> List[Track]:
        """Greedy Algorithm for Infinite Flow"""
        if not pool and not seeds:
            return []

        chain: List[Dict[str, Any]] = []
        used_ids = set()

        for s in seeds:
            chain.append(s)
            used_ids.add(s["id"])

        if not chain:
            def start_score(node):
                t = node["track"]
                score = 0
                if "energy" in vibe_params: score -= abs(t.energy - vibe_params["energy"])
                return score
            
            pool.sort(key=start_score, reverse=True)
            import random
            start_node = random.choice(pool[:min(10, len(pool))])
            chain.append(start_node)
            used_ids.add(start_node["id"])

        while len(chain) < target_length:
            current_node = chain[-1]
            best_next = None
            best_score = -999.0
            
            for candidate in pool:
                if candidate["id"] in used_ids:
                    continue
                
                mix_score = self._calculate_transition_score(current_node, candidate)
                
                vibe_score = 0.0
                if "energy" in vibe_params:
                    vibe_score -= abs(candidate["track"].energy - vibe_params["energy"]) * 0.1
                
                total_score = mix_score + vibe_score
                
                if total_score > best_score:
                    best_score = total_score
                    best_next = candidate
            
            if best_next:
                chain.append(best_next)
                used_ids.add(best_next["id"])
            else:
                break
                
        return [node["track"] for node in chain]

    def build_path(
        self,
        pool: List[Dict[str, Any]],
        start_node: Dict[str, Any],
        end_node: Dict[str, Any],
        steps: int
    ) -> List[Track]:
        """
        Pathfinding (Bridge Mode): StartとEndの間を滑らかに埋める
        """
        chain = [start_node]
        used_ids = {start_node["id"], end_node["id"]}
        current_node = start_node
        
        # 中間ステップ数
        intermediate_steps = max(0, steps - 2)
        
        for i in range(intermediate_steps):
            progress = (i + 1) / (intermediate_steps + 1)
            
            # Linear interpolation of BPM/Energy target
            target_bpm = start_node["track"].bpm + (end_node["track"].bpm - start_node["track"].bpm) * progress
            target_energy = start_node["track"].energy + (end_node["track"].energy - start_node["track"].energy) * progress
            
            best_next = None
            best_score = -999.0
            
            for candidate in pool:
                if candidate["id"] in used_ids: continue
                
                # 1. Mixability from Current
                mix_score = self._calculate_transition_score(current_node, candidate)
                
                # 2. Vector Similarity to End Node (Guide towards goal)
                goal_sim = 0.0
                if candidate["vector"] is not None and end_node["vector"] is not None:
                     dot = np.dot(candidate["vector"], end_node["vector"])
                     nA = np.linalg.norm(candidate["vector"])
                     nB = np.linalg.norm(end_node["vector"])
                     if nA and nB: goal_sim = dot / (nA * nB)

                # 3. Param proximity to interpolation target
                param_score = 0.0
                if candidate["track"].bpm > 0:
                    param_score -= abs(candidate["track"].bpm - target_bpm) * 0.01
                param_score -= abs(candidate["track"].energy - target_energy)
                
                # Weighted Sum
                total_score = (mix_score * 1.5) + (goal_sim * 1.0) + (param_score * 0.5)
                
                if total_score > best_score:
                    best_score = total_score
                    best_next = candidate
            
            if best_next:
                chain.append(best_next)
                used_ids.add(best_next["id"])
                current_node = best_next
            else:
                break
        
        chain.append(end_node)
        return [node["track"] for node in chain]

    def _calculate_transition_score(self, current: Dict[str, Any], candidate: Dict[str, Any]) -> float:
        """ラッパー: utilsの計算ロジックを呼び出す"""
        vec_sim = 0.0
        if current["vector"] is not None and candidate["vector"] is not None:
            dot = np.dot(current["vector"], candidate["vector"])
            nA = np.linalg.norm(current["vector"])
            nB = np.linalg.norm(candidate["vector"])
            if nA and nB: vec_sim = dot / (nA * nB)
            
        return calculate_mixability_score(
            target_bpm=current["track"].bpm,
            target_key=current["track"].key,
            candidate_bpm=candidate["track"].bpm,
            candidate_key=candidate["track"].key,
            vector_similarity=vec_sim,
            weights={"bpm": 0.4, "key": 0.3, "vector": 0.3} # 繋ぎ重視の重み配分
        )

recommendation_engine = RecommendationEngine()
setlist_builder = SetlistBuilder()