from typing import List, Optional, Dict, Any
from sqlmodel import Session, select
from datetime import datetime
import json
import os
import random
import numpy as np

from domain.models.setlist import Setlist, SetlistTrack
from domain.models.track import Track, TrackEmbedding
from domain.models.lyrics import Lyrics
from infra.repositories.setlist_repository import SetlistRepository
from infra.repositories.track_repository import TrackRepository
from infra.repositories.recommendation_repository import RecommendationRepository
from domain.services.setlist_builder import SetlistBuilder
from infra.database.connection import get_setting_value

from utils.llm import generate_vibe_parameters
from utils.audio_math import calculate_mixability_score

class SetlistAppService:
    def __init__(self, session: Session):
        self.session = session
        self.repository = SetlistRepository(session)
        self.track_repository = TrackRepository(session)
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

        # 削除・挿入・updated_at 更新を単一トランザクションで行う
        # (途中で失敗した場合に旧データが消えるのを防ぐ)
        self.repository.clear_tracks(setlist_id, commit=False)

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

        setlist.updated_at = datetime.now()
        self.session.add(setlist)
        try:
            self.session.commit()
        except Exception:
            self.session.rollback()
            raise
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
            if track.filepath and not os.path.exists(track.filepath):
                lines.append(f"# MISSING: {artist} - {title_text} ({track.filepath})")
                continue
            lines.append(f"#EXTINF:{duration},{artist} - {title_text}")
            if track.filepath:
                lines.append(track.filepath)
        return "\n".join(lines)

    def validate_export(self, setlist_id: int) -> Dict[str, Any]:
        """エクスポート前にファイルの存在を検証し、欠落している曲を返す"""
        setlist = self.repository.get_by_id(setlist_id)
        if not setlist:
            raise ValueError("Setlist not found")

        results = self.repository.get_tracks(setlist_id)
        missing = []
        for st, track, _lyrics_content in results:
            if not track.filepath or not os.path.exists(track.filepath):
                missing.append({
                    "id": track.id,
                    "title": track.title,
                    "artist": track.artist,
                    "filepath": track.filepath,
                })
        return {"total": len(results), "missing": missing}

    def recommend_next_track(
        self,
        track_id: int,
        limit: int = 20,
        vibe: Optional[str] = None,
        genres: Optional[List[str]] = None,
        subgenres: Optional[List[str]] = None
    ) -> List[Dict[str, Any]]:
        target_track = self.track_repository.get_by_id(track_id)
        if not target_track:
            raise ValueError("Track not found")

        vibe_params = {}
        if vibe:
            vibe_params = generate_vibe_parameters(vibe, session=self.session)

        if "bpm" not in vibe_params:
            vibe_params["bpm"] = target_track.bpm

        pool = self.recommendation_repository.fetch_candidates_pool(
            vibe_params,
            genres=genres,
            subgenres=subgenres,
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
        vibe: str,
        limit: Optional[int] = None,
        min_length: Optional[int] = None,
        max_length: Optional[int] = None,
        seed_track_ids: Optional[List[int]] = None,
        genres: Optional[List[str]] = None,
        subgenres: Optional[List[str]] = None
    ) -> List[Dict[str, Any]]:
        # 曲数解決: limit > min/max 両方 > min のみ > max のみ > UI 設定のデフォルト値
        if limit is not None:
            target_length = limit
        elif min_length is not None and max_length is not None:
            target_length = random.randint(min_length, max_length)
        elif min_length is not None:
            target_length = min_length
        elif max_length is not None:
            target_length = max_length
        else:
            try:
                target_length = int(get_setting_value(self.session, "setlist_default_length", "10"))
            except (TypeError, ValueError):
                target_length = 10

        vibe_params = generate_vibe_parameters(vibe, session=self.session)

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
            subgenres=subgenres,
            limit=300,
            exclude_ids=exclude_ids
        )

        # pool と seeds から Track オブジェクトのリストを取得
        result_tracks = self.setlist_builder.build_chain(pool, seeds, target_length, vibe_params)
        
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
        genres: Optional[List[str]] = None,
        subgenres: Optional[List[str]] = None
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
            {"bpm": ((start_track.bpm or 0) + (end_track.bpm or 0)) / 2},
            genres=genres,
            subgenres=subgenres,
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

    def generate_wordplay_setlist(
        self,
        start_track_id: int,
        length: int = 10,
        genres: Optional[List[str]] = None,
        subgenres: Optional[List[str]] = None
    ) -> List[Dict[str, Any]]:
        """開始曲から、歌詞キーワードの一致（ワードプレイ）で曲を繋いだチェーンを構築する。"""
        from api.routers.lyrics import analyze_lyrics, search_lyrics

        start_track = self.track_repository.get_by_id(start_track_id)
        if not start_track:
            raise ValueError("Track not found")

        chain: List[Track] = [start_track]
        used_ids = {start_track.id}

        while len(chain) < length:
            current = chain[-1]
            keywords = analyze_lyrics(current.id, False, self.session)

            candidates = []  # (score, track)
            for kw in keywords:
                results = search_lyrics(kw["keyword"], exclude_track_id=current.id, session=self.session)
                for r in results:
                    cand_track_id = r["track"]["id"]
                    if cand_track_id in used_ids:
                        continue
                    if genres and r["track"].get("genre") not in genres:
                        continue
                    if subgenres and r["track"].get("subgenre") not in subgenres:
                        continue
                    cand_track = self.track_repository.get_by_id(cand_track_id)
                    if not cand_track:
                        continue
                    score = kw["count"] * 0.5 + calculate_mixability_score(
                        target_bpm=current.bpm,
                        target_key=current.key,
                        candidate_bpm=cand_track.bpm,
                        candidate_key=cand_track.key,
                        vector_similarity=0.0
                    )
                    candidates.append((score, cand_track))

            if not candidates:
                break

            candidates.sort(key=lambda x: x[0], reverse=True)
            best_track = candidates[0][1]
            chain.append(best_track)
            used_ids.add(best_track.id)

        return [t.model_dump() for t in chain]