from typing import List, Optional, Dict, Any
from sqlmodel import Session, select
from datetime import datetime
import json
import numpy as np

from domain.models.setlist import Setlist, SetlistTrack
from domain.models.track import Track, TrackEmbedding
from domain.models.preset import Preset
from domain.models.prompt import Prompt
from domain.models.lyrics import Lyrics
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
        for st, t, lyrics_content in results:
            t_dict = t.model_dump()
            t_dict["setlist_track_id"] = st.id
            t_dict["position"] = st.position
            t_dict["wordplay_json"] = st.wordplay_json
            # JOIN結果から歌詞の有無を判定
            t_dict["has_lyrics"] = bool(lyrics_content and lyrics_content.strip())
            tracks.append(t_dict)
        return tracks

    def update_setlist_tracks(self, setlist_id: int, track_data: List[Any]) -> bool:
        setlist = self.repository.get_by_id(setlist_id)
        if not setlist:
            return False
        
        self.repository.clear_tracks(setlist_id)
        
        for i, data in enumerate(track_data):
            if isinstance(data, dict):
                tid = data.get("id")
                wp_json = data.get("wordplay_json")
            else:
                tid = data
                wp_json = None
            
            if tid is None: continue

            st = SetlistTrack(
                setlist_id=setlist_id, 
                track_id=tid, 
                position=i,
                wordplay_json=wp_json
            )
            self.session.add(st)
        
        self.session.commit()
        setlist.updated_at = datetime.now()
        self.session.add(setlist)
        self.session.commit()
        return True

    def export_as_m3u8(self, setlist_id: int) -> str:
        setlist = self.repository.get_by_id(setlist_id)
        if not setlist:
            raise ValueError("Setlist not found")

        results = self.repository.get_tracks(setlist_id)
        lines = ["#EXTM3U"]
        for st, track, lyrics_content in results:
            duration = int(track.duration) if track.duration else -1
            artist = track.artist or "Unknown Artist"
            title_text = track.title or "Unknown Title"
            lines.append(f"#EXTINF:{duration},{artist} - {title_text}")
            if track.filepath:
                lines.append(track.filepath)
        return "\n".join(lines)

    def recommend_next_track(
        self, 
        track_id: int, 
        limit: int = 20, 
        preset_id: Optional[int] = None,
        genres: Optional[List[str]] = None
    ) -> List[Dict[str, Any]]:
        target_track = self.track_repository.get_by_id(track_id)
        if not target_track:
            raise ValueError("Track not found")

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
                nA, nB = np.linalg.norm(target_vec), np.linalg.norm(cand["vector"])
                if nA and nB: vec_sim = dot / (nA * nB)
            
            score = calculate_mixability_score(
                target_bpm=target_track.bpm,
                target_key=target_track.key,
                candidate_bpm=cand["track"].bpm,
                candidate_key=cand["track"].key,
                vector_similarity=vec_sim
            )
            
            track_dict = cand["track"].model_dump()
            # リポジトリの pool 取得時に計算された has_lyrics を注入
            track_dict["has_lyrics"] = cand.get("has_lyrics", False)
            scored_candidates.append((track_dict, score))
        
        scored_candidates.sort(key=lambda x: x[1], reverse=True)
        return [c[0] for c in scored_candidates[:limit]]

    def generate_auto_setlist(
        self, 
        preset_id: int, 
        limit: int = 10, 
        seed_track_ids: Optional[List[int]] = None, 
        genres: Optional[List[str]] = None
    ) -> List[Dict[str, Any]]:
        preset = self.preset_repository.get_by_id(preset_id)
        if not preset:
            raise ValueError("Preset not found")

        prompt_content = ""
        if preset.prompt_id:
            prompt = self.prompt_repository.get_by_id(preset.prompt_id)
            prompt_content = prompt.content if prompt else ""
            
        vibe_params = generate_vibe_parameters(prompt_content, session=self.session)

        seeds = []
        if seed_track_ids:
            seed_objs = self.session.exec(select(Track).where(Track.id.in_(seed_track_ids))).all()
            for t in seed_objs:
                emb = self.session.get(TrackEmbedding, t.id)
                vec = self.recommendation_repository._parse_embedding(emb.embedding_json) if emb else None
                # シード曲についても歌詞情報を取得
                ly = self.session.get(Lyrics, t.id)
                seeds.append({
                    "id": t.id, 
                    "track": t, 
                    "vector": vec,
                    "has_lyrics": bool(ly and ly.content.strip())
                })

        exclude_ids = seed_track_ids or []
        pool = self.recommendation_repository.fetch_candidates_pool(
            vibe_params, 
            genres=genres, 
            limit=300, 
            exclude_ids=exclude_ids
        )

        # pool と seeds から Track オブジェクトのリストを取得
        result_tracks = self.setlist_builder.build_chain(pool, seeds, limit, vibe_params)
        
        enriched_result = []
        for t_obj in result_tracks:
            t_dict = t_obj.model_dump()
            # pool または seeds から has_lyrics 情報を探して再注入
            matching_cand = next((c for c in pool if c["id"] == t_obj.id), None)
            if not matching_cand:
                matching_cand = next((s for s in seeds if s["id"] == t_obj.id), None)
            
            t_dict["has_lyrics"] = matching_cand.get("has_lyrics", False) if matching_cand else False
            enriched_result.append(t_dict)
        
        return enriched_result

    def generate_path_setlist(
        self,
        start_track_id: int,
        end_track_id: int,
        length: int,
        genres: Optional[List[str]] = None
    ) -> List[Dict[str, Any]]:
        start_track = self.track_repository.get_by_id(start_track_id)
        end_track = self.track_repository.get_by_id(end_track_id)
        if not start_track or not end_track:
            raise ValueError("Start or End track not found")

        def make_node(t):
            emb = self.session.get(TrackEmbedding, t.id)
            vec = self.recommendation_repository._parse_embedding(emb.embedding_json) if emb else None
            ly = self.session.get(Lyrics, t.id)
            return {
                "id": t.id, 
                "track": t, 
                "vector": vec,
                "has_lyrics": bool(ly and ly.content.strip())
            }
        
        start_node = make_node(start_track)
        end_node = make_node(end_track)
        
        pool = self.recommendation_repository.fetch_candidates_pool(
            {"bpm": (start_track.bpm + end_track.bpm) / 2},
            genres=genres,
            limit=400,
            exclude_ids=[start_track_id, end_track_id]
        )
        
        result_tracks = self.setlist_builder.build_path(pool, start_node, end_node, length)
        
        enriched_result = []
        for t_obj in result_tracks:
            t_dict = t_obj.model_dump()
            # pool, start, end から has_lyrics 情報をマッピング
            matching_cand = next((c for c in pool if c["id"] == t_obj.id), None)
            if matching_cand:
                t_dict["has_lyrics"] = matching_cand.get("has_lyrics", False)
            elif t_obj.id == start_track_id:
                t_dict["has_lyrics"] = start_node["has_lyrics"]
            elif t_obj.id == end_track_id:
                t_dict["has_lyrics"] = end_node["has_lyrics"]
            else:
                t_dict["has_lyrics"] = False
                
            enriched_result.append(t_dict)
            
        return enriched_result