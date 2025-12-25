from typing import List, Optional, Dict, Any, Union
from sqlmodel import Session, select, or_, and_, col, text
from sqlalchemy import func
import json

from domain.models.track import Track, TrackEmbedding
from domain.models.lyrics import Lyrics

class TrackRepository:
    def __init__(self, session: Session):
        self.session = session

    def get_by_id(self, track_id: int) -> Optional[Track]:
        return self.session.get(Track, track_id)

    def find_all(self, offset: int = 0, limit: int = 100) -> List[Track]:
        return self.session.exec(select(Track).offset(offset).limit(limit)).all()

    def update_genre(self, track_id: int, genre: str, verified: bool = True) -> Optional[Track]:
        track = self.get_by_id(track_id)
        if track:
            track.genre = genre
            track.is_genre_verified = verified
            self.session.add(track)
            self.session.commit()
            self.session.refresh(track)
        return track

    def get_similar_tracks(self, track_id: int, limit: int = 20) -> List[Track]:
        """ベクトル検索: 指定された track_id に類似するトラックを取得する"""
        target_embedding = self.session.exec(
            select(TrackEmbedding).where(TrackEmbedding.track_id == track_id)
        ).first()
        
        if not target_embedding:
            raise ValueError("Track embedding not found. Please analyze the track first.")

        try:
            vec_str = target_embedding.embedding_json
            query = select(Track).join(TrackEmbedding)
            query = query.where(Track.id != track_id)
            # DuckDB 独自の array_cosine_similarity を使用
            query = query.order_by(text(f"array_cosine_similarity(CAST(track_embeddings.embedding_json AS FLOAT[200]), CAST('{vec_str}' AS FLOAT[200])) DESC"))
            query = query.limit(limit)
            
            return self.session.exec(query).all()
        except Exception as e:
            print(f"Vector search error: {e}")
            raise e

    def _apply_search_conditions(
        self,
        query,
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
        min_year: Optional[int] = None,
        max_year: Optional[int] = None,
        year_status: str = "all",
        lyrics_status: str = "all",
        lyrics: Optional[str] = None,
        target_params: Optional[Dict[str, float]] = None,
        already_joined_lyrics: bool = False
    ):
        """検索条件や Vibe パラメータをクエリに適用する内部ヘルパー"""
        
        # 1. Vibe 検索 (LLM 推論値との距離でソート)
        if target_params:
            if min_year is None and "year_min" in target_params:
                min_year = int(target_params["year_min"])
            if max_year is None and "year_max" in target_params:
                max_year = int(target_params["year_max"])

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

            query = query.order_by(dist_expr)
        else:
            query = query.order_by(Track.created_at.desc())
        
        # 2. 解析ステータスフィルタ
        if status == "analyzed":
            query = query.where(Track.bpm > 0)
        elif status == "unanalyzed":
            query = query.where(or_(Track.bpm == None, Track.bpm == 0))
        
        # 3. 基本メタデータフィルタ
        if title: query = query.where(col(Track.title).ilike(f"%{title}%"))
        if artist: query = query.where(col(Track.artist).ilike(f"%{artist}%"))
        if album: query = query.where(col(Track.album).ilike(f"%{album}%"))
        
        # 4. リリース年フィルタ
        if year_status == "set":
            query = query.where(and_(Track.year.is_not(None), Track.year > 0))
        elif year_status == "unset":
            query = query.where(or_(Track.year.is_(None), Track.year == 0))
        
        if min_year is not None: query = query.where(Track.year >= min_year)
        if max_year is not None: query = query.where(Track.year <= max_year)

        # 5. 歌詞ステータスフィルタ (確実なサブクエリ方式)
        # JOINの結果に依存せず、IN/NOT IN句で物理的にIDを絞り込みます
        if lyrics_status != "all":
            # 有効な歌詞（NULLでなく、トリム後も空でない）を持つIDを取得するサブクエリ
            # DuckDBのNOT INの挙動(NULL対策)のため、必ず track_id IS NOT NULL を含める
            valid_lyrics_ids = select(Lyrics.track_id).where(
                and_(
                    Lyrics.track_id != None,
                    Lyrics.content != None,
                    func.trim(Lyrics.content) != ""
                )
            )

            if lyrics_status == "set":
                query = query.where(Track.id.in_(valid_lyrics_ids))
            elif lyrics_status == "unset":
                query = query.where(Track.id.not_in(valid_lyrics_ids))
        
        # 歌詞テキスト検索用の結合 (必要に応じて追加)
        if lyrics:
            if not already_joined_lyrics:
                query = query.outerjoin(Lyrics, Track.id == Lyrics.track_id)
            query = query.where(col(Lyrics.content).ilike(f"%{lyrics}%"))

        # 6. ジャンルフィルタ
        if genres:
            query = query.where(or_(col(Track.genre).in_(genres), col(Track.subgenre).in_(genres)))
        
        # 7. キー / スケールフィルタ
        if key and key != "":
            if key in ["Major", "Minor"]:
                query = query.where(col(Track.key).like(f"%{key}"))
            else:
                query = query.where(Track.key == key)
        
        # 8. BPMフィルタ (± bpm_range)
        if bpm and bpm > 0:
            targets = [bpm, bpm * 0.5, bpm * 2.0]
            bpm_conditions = [
                and_(Track.bpm >= (t - bpm_range), Track.bpm <= (t + bpm_range))
                for t in targets
            ]
            query = query.where(or_(*bpm_conditions))
        
        # 9. その他オーディオ特徴量フィルタ
        if min_energy is not None: query = query.where(Track.energy >= min_energy)
        if max_energy is not None: query = query.where(Track.energy <= max_energy)
        if min_danceability is not None: query = query.where(Track.danceability >= min_danceability)
        if max_danceability is not None: query = query.where(Track.danceability <= max_danceability)
        if min_brightness is not None: query = query.where(Track.brightness >= min_brightness)
        if max_brightness is not None: query = query.where(Track.brightness <= max_brightness)
        if min_duration is not None: query = query.where(Track.duration >= min_duration)
        if max_duration is not None: query = query.where(Track.duration <= max_duration)
            
        return query

    def search_tracks(
        self,
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
        min_year: Optional[int] = None,
        max_year: Optional[int] = None,
        year_status: str = "all",
        lyrics_status: str = "all",
        lyrics: Optional[str] = None,
        target_params: Optional[Dict[str, float]] = None,
        limit: int = 100, 
        offset: int = 0
    ) -> List[Dict[str, Any]]:
        """楽曲検索を実行し、歌詞情報を注入した結果を返す"""
        
        # 表示用の歌詞カラム取得のために常に outerjoin する
        query = select(Track, Lyrics.content).outerjoin(Lyrics, Track.id == Lyrics.track_id)
        
        query = self._apply_search_conditions(
            query=query,
            status=status,
            title=title,
            artist=artist,
            album=album,
            genres=genres,
            key=key,
            bpm=bpm,
            bpm_range=bpm_range,
            min_duration=min_duration,
            max_duration=max_duration,
            min_energy=min_energy,
            max_energy=max_energy,
            min_danceability=min_danceability,
            max_danceability=max_danceability,
            min_brightness=min_brightness,
            max_brightness=max_brightness,
            min_year=min_year,
            max_year=max_year,
            year_status=year_status,
            lyrics_status=lyrics_status,
            lyrics=lyrics,
            target_params=target_params,
            already_joined_lyrics=True
        )
        
        query = query.offset(offset).limit(limit)
        results = self.session.exec(query).all()
        
        final_tracks = []
        for track, lyrics_content in results:
            track_data = track.model_dump()
            track_data["lyrics"] = lyrics_content
            track_data["has_lyrics"] = bool(lyrics_content and lyrics_content.strip())
            final_tracks.append(track_data)
            
        return final_tracks

    def search_track_ids(
        self,
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
        min_year: Optional[int] = None,
        max_year: Optional[int] = None,
        year_status: str = "all",
        lyrics_status: str = "all",
        lyrics: Optional[str] = None,
        target_params: Optional[Dict[str, float]] = None
    ) -> List[int]:
        """IDのみのリストを返す（一括操作用）"""
        
        query = select(Track.id)
        
        query = self._apply_search_conditions(
            query=query,
            status=status,
            title=title,
            artist=artist,
            album=album,
            genres=genres,
            key=key,
            bpm=bpm,
            bpm_range=bpm_range,
            min_duration=min_duration,
            max_duration=max_duration,
            min_energy=min_energy,
            max_energy=max_energy,
            min_danceability=min_danceability,
            max_danceability=max_danceability,
            min_brightness=min_brightness,
            max_brightness=max_brightness,
            min_year=min_year,
            max_year=max_year,
            year_status=year_status,
            lyrics_status=lyrics_status,
            lyrics=lyrics,
            target_params=target_params,
            already_joined_lyrics=False
        )
        
        return self.session.exec(query).all()