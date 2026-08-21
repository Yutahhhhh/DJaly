from typing import Any, Dict, List, Optional

from mcp_server.instance import mcp, db_session, serialize, track_list_payload
from app.services.track_app_service import TrackAppService
from app.services.recommendation_app_service import RecommendationAppService
from utils.llm import generate_vibe_parameters


@mcp.tool()
def search_tracks(
    q: Optional[str] = None,
    title: Optional[str] = None,
    artist: Optional[str] = None,
    album: Optional[str] = None,
    genres: Optional[List[str]] = None,
    subgenres: Optional[List[str]] = None,
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
    status: str = "all",
    limit: int = 50,
    offset: int = 0,
) -> Dict[str, Any]:
    """ライブラリの楽曲を条件で検索する。q はタイトル/アーティスト横断のフリーテキスト検索。
    genres/subgenres は完全一致リスト。status='verified'|'unverified'|'all' でジャンル検証状態を絞れる。
    自然言語の「雰囲気」で検索したい場合は vibe_search を使うこと。"""
    with db_session() as session:
        service = TrackAppService(session)
        tracks = service.get_tracks(
            status=status, q=q, title=title, artist=artist, album=album,
            genres=genres, subgenres=subgenres, key=key, bpm=bpm, bpm_range=bpm_range,
            min_duration=min_duration, max_duration=max_duration,
            min_energy=min_energy, max_energy=max_energy,
            min_danceability=min_danceability, max_danceability=max_danceability,
            min_brightness=min_brightness, max_brightness=max_brightness,
            min_year=min_year, max_year=max_year,
            year_status=year_status, lyrics_status=lyrics_status, lyrics=lyrics,
            limit=limit, offset=offset,
        )
        return track_list_payload(tracks)


@mcp.tool()
def vibe_search(
    prompt: str,
    genres: Optional[List[str]] = None,
    subgenres: Optional[List[str]] = None,
    limit: int = 50,
    offset: int = 0,
) -> Dict[str, Any]:
    """自然言語の「雰囲気」（例: '夜のドライブ用チルR&B', 'peak time techno'）をAIでBPM/エナジー/
    ダンサビリティ等の特徴量に変換し、それに近い楽曲を検索する。結果には解釈されたパラメータ
    (resolved_params) も含まれるので、意図通りか確認できる。"""
    with db_session() as session:
        service = TrackAppService(session)
        tracks = service.get_tracks(
            vibe_prompt=prompt, genres=genres, subgenres=subgenres,
            limit=limit, offset=offset,
        )
        resolved_params = generate_vibe_parameters(prompt, session=session)
        payload = track_list_payload(tracks)
        payload["resolved_params"] = resolved_params
        return payload


@mcp.tool()
def get_track_similar(track_id: int, limit: int = 20) -> Dict[str, Any]:
    """指定した楽曲に音響的に似ている楽曲をベクトル類似検索で取得する（ミックスの繋ぎ候補選びに便利）。"""
    with db_session() as session:
        service = TrackAppService(session)
        tracks = service.get_similar_tracks(track_id, limit)
        return track_list_payload(tracks)


@mcp.tool()
def suggest_track_genre(track_id: int) -> Dict[str, Any]:
    """類似曲の実績ジャンルから、指定楽曲に合いそうなジャンルを推測する（LLMは使わずベクトル類似ベース）。"""
    with db_session() as session:
        service = RecommendationAppService(session)
        return serialize(service.suggest_genre(track_id))


@mcp.tool()
def update_track_genre(track_id: int, genre: str) -> Dict[str, Any]:
    """楽曲のジャンルを手動で更新する。"""
    with db_session() as session:
        service = TrackAppService(session)
        track = service.update_genre(track_id, genre)
        if not track:
            raise ValueError(f"Track {track_id} not found")
        return serialize(track)


@mcp.tool()
def update_track_info(
    track_id: int,
    title: Optional[str] = None,
    artist: Optional[str] = None,
    album: Optional[str] = None,
    year: Optional[int] = None,
) -> Dict[str, Any]:
    """楽曲のタイトル/アーティスト/アルバム/年を更新する。指定したフィールドのみ変更される。"""
    with db_session() as session:
        from domain.models.track import Track

        track = session.get(Track, track_id)
        if not track:
            raise ValueError(f"Track {track_id} not found")
        if title is not None:
            track.title = title
        if artist is not None:
            track.artist = artist
        if album is not None:
            track.album = album
        if year is not None:
            track.year = year
        session.add(track)
        session.commit()
        session.refresh(track)
        return serialize(track)
