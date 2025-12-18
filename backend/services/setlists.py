from typing import List, Optional, Dict, Any
from sqlmodel import Session, select, desc, col
from datetime import datetime
import json
import numpy as np

from models import Setlist, SetlistTrack, Track, Preset, Prompt, TrackEmbedding
from services.recommendation import recommendation_engine, setlist_builder
from utils.llm import generate_vibe_parameters
from utils.audio_math import calculate_mixability_score

class SetlistService:
    def get_setlists(self, session: Session) -> List[Setlist]:
        return session.exec(select(Setlist).order_by(desc(Setlist.updated_at))).all()

    def create_setlist(self, session: Session, name: str) -> Setlist:
        setlist = Setlist(name=name)
        session.add(setlist)
        session.commit()
        session.refresh(setlist)
        return setlist

    def update_setlist(self, session: Session, setlist_id: int, setlist_data: Dict[str, Any]) -> Optional[Setlist]:
        setlist = session.get(Setlist, setlist_id)
        if not setlist: return None
        for key, value in setlist_data.items():
            if hasattr(setlist, key): setattr(setlist, key, value)
        setlist.updated_at = datetime.now()
        session.add(setlist)
        session.commit()
        session.refresh(setlist)
        return setlist

    def delete_setlist(self, session: Session, setlist_id: int) -> bool:
        setlist = session.get(Setlist, setlist_id)
        if not setlist: return False
        tracks = session.exec(select(SetlistTrack).where(SetlistTrack.setlist_id == setlist_id)).all()
        for t in tracks: session.delete(t)
        session.delete(setlist)
        session.commit()
        return True

    def get_setlist_tracks(self, session: Session, setlist_id: int) -> List[Dict[str, Any]]:
        query = (
            select(SetlistTrack, Track)
            .where(SetlistTrack.setlist_id == setlist_id)
            .where(SetlistTrack.track_id == Track.id)
            .order_by(SetlistTrack.position)
        )
        results = session.exec(query).all()
        tracks = []
        for st, t in results:
            t_dict = t.dict()
            t_dict["setlist_track_id"] = st.id
            t_dict["position"] = st.position
            tracks.append(t_dict)
        return tracks

    def update_setlist_tracks(self, session: Session, setlist_id: int, track_ids: List[int]) -> bool:
        setlist = session.get(Setlist, setlist_id)
        if not setlist: return False
        existing = session.exec(select(SetlistTrack).where(SetlistTrack.setlist_id == setlist_id)).all()
        for e in existing: session.delete(e)
        for i, tid in enumerate(track_ids):
            session.add(SetlistTrack(setlist_id=setlist_id, track_id=tid, position=i))
        setlist.updated_at = datetime.now()
        session.add(setlist)
        session.commit()
        return True

    def export_as_m3u8(self, session: Session, setlist_id: int) -> str:
        """
        セットリストをM3U8形式の文字列として生成する。
        """
        setlist = session.get(Setlist, setlist_id)
        if not setlist:
            raise ValueError("Setlist not found")

        # 順序通りにトラックを取得
        query = (
            select(SetlistTrack, Track)
            .where(SetlistTrack.setlist_id == setlist_id)
            .where(SetlistTrack.track_id == Track.id)
            .order_by(SetlistTrack.position)
        )
        results = session.exec(query).all()

        # M3U8 Header
        lines = ["#EXTM3U"]

        for st, track in results:
            # EXTINF: duration, Artist - Title
            try:
                duration = int(track.duration) if track.duration else -1
            except:
                duration = -1
            
            artist = track.artist if track.artist else "Unknown Artist"
            title_text = track.title if track.title else "Unknown Title"
            title = f"{artist} - {title_text}"
            
            lines.append(f"#EXTINF:{duration},{title}")
            # File Path
            if track.filepath:
                lines.append(track.filepath)

        return "\n".join(lines)

    # --- New Logic: Recommendation & Auto-Gen ---

    def recommend_next_track(
        self, 
        session: Session, 
        track_id: int, 
        limit: int = 20, 
        preset_id: Optional[int] = None,
        genres: Optional[List[str]] = None
    ) -> List[Track]:
        """
        指定されたトラックに続く曲を提案する。
        LLMは検索条件のバイアス（Vibeパラメータ）として使用する。
        """
        target_track = session.get(Track, track_id)
        if not target_track: raise ValueError("Track not found")

        vibe_params = {}
        if preset_id:
            preset = session.get(Preset, preset_id)
            if preset and preset.prompt_id:
                prompt = session.get(Prompt, preset.prompt_id)
                if prompt:
                    ctx = f"Reference: {target_track.title}. Goal: {prompt.content}"
                    vibe_params = generate_vibe_parameters(ctx, session=session)

        # 2. Fetch Candidates (DuckDB Engine)
        # レコメンドの場合はターゲットBPMに近いものを中心にプールを作成
        if "bpm" not in vibe_params:
            vibe_params["bpm"] = target_track.bpm

        pool = recommendation_engine.fetch_candidates_pool(
            session, 
            vibe_params, 
            genres=genres, 
            limit=200, 
            exclude_ids=[track_id]
        )

        # 3. Score & Sort (Python Logic)
        target_vec = None
        target_emb = session.get(TrackEmbedding, track_id)
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
        session: Session, 
        preset_id: int, 
        limit: int = 10, 
        seed_track_ids: Optional[List[int]] = None, 
        genres: Optional[List[str]] = None
    ) -> List[Track]:
        """
        LLMでVibeを解析し、Pythonアルゴリズムでセットリストを連鎖的に構築する。
        """
        preset = session.get(Preset, preset_id)
        if not preset: raise ValueError("Preset not found")

        prompt_content = ""
        if preset.prompt_id:
            prompt = session.get(Prompt, preset.prompt_id)
            prompt_content = prompt.content if prompt else ""
            
        vibe_params = generate_vibe_parameters(prompt_content, session=session)
        print(f"DEBUG: AutoGen Vibe Params: {vibe_params}")

        seeds = []
        if seed_track_ids:
            seed_objs = session.exec(select(Track).where(Track.id.in_(seed_track_ids))).all()
            for t in seed_objs:
                emb = session.get(TrackEmbedding, t.id)
                vec = None
                if emb and emb.embedding_json:
                    try:
                        import numpy as np
                        vec = np.array(json.loads(emb.embedding_json))
                    except: pass
                seeds.append({"id": t.id, "track": t, "vector": vec})

        exclude_ids = seed_track_ids or []
        pool = recommendation_engine.fetch_candidates_pool(
            session, 
            vibe_params, 
            genres=genres, 
            limit=300, 
            exclude_ids=exclude_ids
        )

        result_tracks = setlist_builder.build_chain(pool, seeds, limit, vibe_params)
        
        return result_tracks

    def generate_path_setlist(
        self,
        session: Session,
        start_track_id: int,
        end_track_id: int,
        length: int,
        genres: Optional[List[str]] = None
    ) -> List[Track]:
        """Pathfinding: 2曲間を繋ぐ"""
        start_track = session.get(Track, start_track_id)
        end_track = session.get(Track, end_track_id)
        if not start_track or not end_track:
            raise ValueError("Start or End track not found")

        def make_node(t):
            emb = session.get(TrackEmbedding, t.id)
            vec = None
            if emb and emb.embedding_json:
                try:
                    import numpy as np
                    vec = np.array(json.loads(emb.embedding_json))
                except: pass
            return {"id": t.id, "track": t, "vector": vec}
        
        start_node = make_node(start_track)
        end_node = make_node(end_track)

        # 未解析トラックはない前提のため、直接BPMを使用
        avg_bpm = (start_track.bpm + end_track.bpm) / 2
        
        vibe_params = {"bpm": avg_bpm} 
        
        pool = recommendation_engine.fetch_candidates_pool(
            session,
            vibe_params,
            genres=genres,
            limit=400,
            exclude_ids=[start_track_id, end_track_id]
        )
        
        # 安全策: build_path が存在するかチェック
        if not hasattr(setlist_builder, "build_path"):
             raise RuntimeError("SetlistBuilder does not have build_path method.")

        path_tracks = setlist_builder.build_path(pool, start_node, end_node, length)
        return path_tracks