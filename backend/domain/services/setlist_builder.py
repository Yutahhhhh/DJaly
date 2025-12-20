from typing import List, Dict, Any
import numpy as np
from domain.models.track import Track
from utils.audio_math import calculate_mixability_score

class SetlistBuilder:
    """
    候補プールから、DJ的なルール（Chain Builder）に従ってセットリストを構築する責務を持つ。
    """
    
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
