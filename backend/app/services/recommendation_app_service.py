from typing import List, Dict, Any, Optional
from sqlmodel import Session
import numpy as np
from infra.repositories.recommendation_repository import RecommendationRepository
from api.schemas.genres import GroupedSuggestionSummary, TrackSuggestion
from domain.models.track import Track

class RecommendationAppService:
    def __init__(self, session: Session):
        self.repository = RecommendationRepository(session)

    def suggest_genre(self, track_id: int, limit: int = 5) -> Dict[str, Optional[str]]:
        target_vec = self.repository.get_track_embedding(track_id)
        
        if target_vec is None:
            return {"suggested_genre": None, "reason": "no_embedding"}
            
        candidates = self.repository.get_verified_tracks_with_embeddings(exclude_track_id=track_id)
        
        if not candidates:
            return {"suggested_genre": None, "reason": "no_verified_tracks"}
            
        genres = []
        vectors = []
        
        for genre, vec in candidates:
            if vec.shape == target_vec.shape:
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

    def get_grouped_suggestions(
        self, 
        limit: int = 10, 
        offset: int = 0, 
        threshold: float = 0.85, 
        summary_only: bool = False,
        mode: str = "genre"
    ) -> List[GroupedSuggestionSummary]:
        parents = self.repository.get_parent_vectors()
        if not parents:
            return []

        candidate_matrix = self.repository.get_candidate_vectors(mode=mode)
        
        if candidate_matrix.size == 0:
            parents.sort(key=lambda x: x[0])
            sliced_parents = parents[offset : offset + limit]
            parent_ids = [p[0] for p in sliced_parents]
            track_map = self.repository.get_tracks_by_ids(parent_ids)
            
            return [GroupedSuggestionSummary(
                parent_track=track_map.get(pid),
                suggestion_count=0,
                suggestions=[]
            ) for pid, _ in sliced_parents if pid in track_map]

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
            
        parent_stats.sort(key=lambda x: (x[1], x[0])) # Sort by count (asc) then ID
        
        sliced_stats = parent_stats[offset : offset + limit]
        if not sliced_stats: return []
        
        parent_ids = [x[0] for x in sliced_stats]
        track_map = self.repository.get_tracks_by_ids(parent_ids)
        
        results = []
        for pid, count in sliced_stats:
            if pid in track_map:
                results.append(GroupedSuggestionSummary(
                    parent_track=track_map[pid],
                    suggestion_count=count,
                    suggestions=[] 
                ))
            
        return results

    def get_suggestions_for_track(self, track_id: int, threshold: float = 0.85) -> List[TrackSuggestion]:
        parent_vec = self.repository.get_track_embedding(track_id)
        
        if parent_vec is None:
            return []

        candidate_ids, candidate_matrix = self.repository.get_candidates_with_ids()
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
        
        track_map = self.repository.get_tracks_by_ids(top_ids)
        
        suggestions = []
        for i, idx in enumerate(top_indices):
            cid = candidate_ids[idx]
            if cid in track_map:
                suggestions.append(TrackSuggestion(
                    track=track_map[cid],
                    similarity=float(matched_sims[i])
                ))
                
        return suggestions
