from typing import Any, Dict, List, Optional

from mcp_server.instance import mcp, db_session, serialize, track_list_payload
from app.services.track_app_service import TrackAppService
from app.services.recommendation_app_service import RecommendationAppService


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
    自然言語の雰囲気は、このツールを呼ぶMCPクライアント自身がBPMや特徴量の
    範囲へ解釈して指定すること。plumdeck内ではLLM推論を行わない。"""
    if not 1 <= limit <= 500 or offset < 0:
        raise ValueError("limit must be 1..500 and offset must be non-negative")
    with db_session() as session:
        service = TrackAppService(session)
        page = service.get_tracks_page(
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
        return {
            "count": len(page["items"]), "tracks": serialize(page["items"]),
            "total": page["total"], "limit": page["limit"], "offset": page["offset"],
            "has_more": page["has_more"],
        }

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
            from mcp.server.mcpserver.exceptions import ToolError
            raise ToolError(f"Track {track_id} not found")
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
