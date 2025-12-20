from typing import List, Optional, Dict, Any
from sqlmodel import Session, select
from datetime import datetime
import json
import numpy as np

from domain.models.setlist import Setlist, SetlistTrack
from domain.models.track import Track, TrackEmbedding
from domain.models.preset import Preset
from domain.models.prompt import Prompt
from infra.repositories.setlist_repository import SetlistRepository
from infra.repositories.track_repository import TrackRepository
from infra.repositories.preset_repository import PresetRepository
from infra.repositories.prompt_repository import PromptRepository
from infra.repositories.recommendation_repository import RecommendationRepository
from domain.services.setlist_builder import SetlistBuilder

from utils.llm import generate_vibe_parameters
from utils.audio_math import calculate_mixability_score

class SetlistAppService:
    def __init__(self, session: Session):
        self.session = session
        self.repository = SetlistRepository(session)
        self.track_repository = TrackRepository(session)
        self.preset_repository = PresetRepository(session)
        self.prompt_repository = PromptRepository(session)
        self.recommendation_repository = RecommendationRepository(session)
        self.setlist_builder = SetlistBuilder()

    def get_setlists(self) -> List[Setlist]:
        return self.repository.find_all()

    def create_setlist(self, name: str) -> Setlist:
        setlist = Setlist(name=name)
        return self.repository.create(setlist)

    def update_setlist(self, setlist_id: int, setlist_data: Dict[str, Any]) -> Optional[Setlist]:
        setlist = self.repository.get_by_id(setlist_id)
        if not setlist:
            return None
        
        for key, value in setlist_data.items():
            if hasattr(setlist, key):
                setattr(setlist, key, value)
        
        return self.repository.update(setlist)

    def delete_setlist(self, setlist_id: int) -> bool:
        setlist = self.repository.get_by_id(setlist_id)
        if not setlist:
            return False
        
        self.repository.clear_tracks(setlist_id)
        self.repository.delete(setlist)
        return True

    def get_setlist_tracks(self, setlist_id: int) -> List[Dict[str, Any]]:
        results = self.repository.get_tracks(setlist_id)
        tracks = []
        for st, t in results:
            t_dict = t.model_dump()
            t_dict["setlist_track_id"] = st.id
            t_dict["position"] = st.position
            tracks.append(t_dict)
        return tracks

    def update_setlist_tracks(self, setlist_id: int, track_ids: List[int]) -> bool:
        setlist = self.repository.get_by_id(setlist_id)
        if not setlist:
            return False
        
        self.repository.clear_tracks(setlist_id)
        
        for i, tid in enumerate(track_ids):
            st = SetlistTrack(setlist_id=setlist_id, track_id=tid, position=i)
            self.repository.add_track(st)
        
        self.session.commit()
        self.repository.update(setlist)
        return True

    def export_as_m3u8(self, setlist_id: int) -> str:
        setlist = self.repository.get_by_id(setlist_id)
        if not setlist:
            raise ValueError("Setlist not found")

        results = self.repository.get_tracks(setlist_id)

        lines = ["#EXTM3U"]

        for st, track in results:
            try:
                duration = int(track.duration) if track.duration else -1
            except:
                duration = -1
            
            artist = track.artist if track.artist else "Unknown Artist"
            title_text = track.title if track.title else "Unknown Title"
            title = f"{artist} - {title_text}"
            
            lines.append(f"#EXTINF:{duration},{title}")
            if track.filepath:
                lines.append(track.filepath)

        return "\n".join(lines)

    def recommend_next_track(
        self, 
        track_id: int, 
        limit: int = 20, 
        preset_id: Optional[int] = None,
        genres: Optional[List[str]] = None
    ) -> List[Track]:
        target_track = self.track_repository.get_by_id(track_id)
        if not target_track: raise ValueError("Track not found")

        vibe_params = {}
        if preset_id:
            preset = self.preset_repository.get_by_id(preset_id)
            if preset and preset.prompt_id:
                prompt = self.prompt_repository.get_by_id(preset.prompt_id)
                if prompt:
                    ctx = f"Reference: {target_track.title}. Goal: {prompt.content}"
                    vibe_params = generate_vibe_parameters(ctx, session=self.session)

        if "bpm" not in vibe_params:
            vibe_params["bpm"] = target_track.bpm

        pool = self.recommendation_repository.fetch_candidates_pool(
            vibe_params, 
            genres=genres, 
            limit=200, 
            exclude_ids=[track_id]
        )

        target_vec = None
        target_emb = self.session.get(TrackEmbedding, track_id)
        if target_emb and target_emb.embedding_json:
            try:
                target_vec = np.array(json.loads(target_emb.embedding_json))
            except: pass

        scored_candidates = []
        for cand in pool:
            vec_sim = 0.0
            if target_vec is not None and cand["vector"] is not None:
                dot = np.dot(target_vec, cand["vector"])
                nA = np.linalg.norm(target_vec)
                nB = np.linalg.norm(cand["vector"])
                if nA and nB: vec_sim = dot / (nA * nB)
            
            score = calculate_mixability_score(
                target_bpm=target_track.bpm,
                target_key=target_track.key,
                candidate_bpm=cand["track"].bpm,
                candidate_key=cand["track"].key,
                vector_similarity=vec_sim
            )
            scored_candidates.append((cand["track"], score))
        
        scored_candidates.sort(key=lambda x: x[1], reverse=True)
        return [c[0] for c in scored_candidates[:limit]]

    def generate_auto_setlist(
        self, 
        preset_id: int, 
        limit: int = 10, 
        seed_track_ids: Optional[List[int]] = None, 
        genres: Optional[List[str]] = None
    ) -> List[Track]:
        preset = self.preset_repository.get_by_id(preset_id)
        if not preset: raise ValueError("Preset not found")

        prompt_content = ""
        if preset.prompt_id:
            prompt = self.prompt_repository.get_by_id(preset.prompt_id)
            prompt_content = prompt.content if prompt else ""
            
        vibe_params = generate_vibe_parameters(prompt_content, session=self.session)
        print(f"DEBUG: AutoGen Vibe Params: {vibe_params}")

        seeds = []
        if seed_track_ids:
            seed_objs = self.session.exec(select(Track).where(Track.id.in_(seed_track_ids))).all()
            for t in seed_objs:
                emb = self.session.get(TrackEmbedding, t.id)
                vec = None
                if emb and emb.embedding_json:
                    try:
                        import numpy as np
                        vec = np.array(json.loads(emb.embedding_json))
                    except: pass
                seeds.append({"id": t.id, "track": t, "vector": vec})

        exclude_ids = seed_track_ids or []
        pool = self.recommendation_repository.fetch_candidates_pool(
            vibe_params, 
            genres=genres, 
            limit=300, 
            exclude_ids=exclude_ids
        )

        result_tracks = self.setlist_builder.build_chain(pool, seeds, limit, vibe_params)
        
        return result_tracks

    def generate_path_setlist(
        self,
        start_track_id: int,
        end_track_id: int,
        length: int,
        genres: Optional[List[str]] = None
    ) -> List[Track]:
        start_track = self.track_repository.get_by_id(start_track_id)
        end_track = self.track_repository.get_by_id(end_track_id)
        if not start_track or not end_track:
            raise ValueError("Start or End track not found")

        def make_node(t):
            emb = self.session.get(TrackEmbedding, t.id)
            vec = None
            if emb and emb.embedding_json:
                try:
                    import numpy as np
                    vec = np.array(json.loads(emb.embedding_json))
                except: pass
            return {"id": t.id, "track": t, "vector": vec}
        
        start_node = make_node(start_track)
        end_node = make_node(end_track)

        avg_bpm = (start_track.bpm + end_track.bpm) / 2
        
        vibe_params = {"bpm": avg_bpm} 
        
        pool = self.recommendation_repository.fetch_candidates_pool(
            vibe_params,
            genres=genres,
            limit=400,
            exclude_ids=[start_track_id, end_track_id]
        )
        
        path_tracks = self.setlist_builder.build_path(pool, start_node, end_node, length)
        return path_tracks
