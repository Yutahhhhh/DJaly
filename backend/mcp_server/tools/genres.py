from typing import Any, Dict, List, Optional

from mcp_server.instance import mcp, db_session, serialize, track_list_payload
from app.services.genre_app_service import GenreAppService
from app.services.recommendation_app_service import RecommendationAppService
from api.schemas.genres import AnalysisMode


@mcp.tool()
def list_genres() -> Dict[str, Any]:
    """ライブラリ内に存在する全ジャンルのユニークな一覧を返す。"""
    with db_session() as session:
        service = GenreAppService(session)
        return {"genres": service.get_all_genres()}


@mcp.tool()
def list_subgenres() -> Dict[str, Any]:
    """ライブラリ内に存在する全サブジャンルのユニークな一覧を返す。"""
    with db_session() as session:
        service = GenreAppService(session)
        return {"subgenres": service.get_all_subgenres()}


@mcp.tool()
def get_unknown_genre_tracks(offset: int = 0, limit: int = 50, mode: str = "genre") -> Dict[str, Any]:
    """ジャンル未検証・未解析の楽曲一覧を返す。mode: genre/subgenre/both。"""
    with db_session() as session:
        service = GenreAppService(session)
        results = service.get_unknown_tracks(offset, limit, AnalysisMode(mode))
        return track_list_payload(results)


@mcp.tool()
def get_genre_analysis_context(
    track_ids: Optional[List[int]] = None,
    mode: str = "both",
    offset: int = 0,
    limit: int = 50,
) -> Dict[str, Any]:
    """ジャンル判定に必要な曲メタデータ、Essentia特徴量、既存語彙、分類ルールを返す。
    このツールを呼んだMCPクライアント自身のLLMで判定し、結果を
    apply_genre_analysis または apply_genre_analyses に渡すこと。
    """
    with db_session() as session:
        service = GenreAppService(session)
        return serialize(service.get_analysis_context(track_ids, AnalysisMode(mode), offset, limit))


@mcp.tool()
def apply_genre_analysis(
    track_id: int,
    genre: Optional[str] = None,
    subgenre: Optional[str] = None,
    confidence: str = "Medium",
    reason: str = "",
    mode: str = "both",
    overwrite: bool = False,
) -> Dict[str, Any]:
    """接続中のMCPクライアントが判定した1曲のジャンル結果を検証して適用する。"""
    with db_session() as session:
        service = GenreAppService(session)
        result = service.apply_genre_analysis(
            track_id,
            {
                "genre": genre,
                "subgenre": subgenre,
                "confidence": confidence,
                "reason": reason,
            },
            AnalysisMode(mode),
            overwrite,
        )
        return {"track_id": track_id, "analysis": serialize(result)}


@mcp.tool()
def apply_genre_analyses(
    analyses: List[Dict[str, Any]],
    mode: str = "both",
    overwrite: bool = False,
) -> Dict[str, Any]:
    """接続中のMCPクライアントが判定した複数曲の結果を一括適用する。
    各要素は track_id, genre, subgenre, confidence, reason を持つ。
    """
    with db_session() as session:
        service = GenreAppService(session)
        results = service.apply_genre_analyses(analyses, AnalysisMode(mode), overwrite)
        return {"results": serialize(results)}


@mcp.tool()
def get_genre_cleanup_suggestions(mode: str = "genre") -> Dict[str, Any]:
    """表記揺れ（例: 'Hip-Hop' vs 'Hip Hop'）があるジャンル/サブジャンルのグループを検出して返す。"""
    with db_session() as session:
        service = GenreAppService(session)
        return {"groups": serialize(service.get_cleanup_suggestions(AnalysisMode(mode)))}


@mcp.tool()
def cleanup_genre_labels(target_genre: str, track_ids: List[int], mode: str = "genre") -> Dict[str, Any]:
    """表記揺れのある楽曲群を、指定した正規のジャンル名 (target_genre) に一括統一する。"""
    with db_session() as session:
        service = GenreAppService(session)
        return serialize(service.execute_cleanup(target_genre, track_ids, AnalysisMode(mode)))


@mcp.tool()
def get_similar_genre_suggestions(track_id: int, threshold: float = 0.85) -> Dict[str, Any]:
    """指定した楽曲に音響特徴が近く、ジャンル統一の候補となる楽曲を類似度付きで返す。"""
    with db_session() as session:
        service = RecommendationAppService(session)
        results = service.get_suggestions_for_track(track_id=track_id, threshold=threshold)
        return {"suggestions": serialize(results)}


@mcp.tool()
def apply_genres_to_files(track_ids: List[int]) -> Dict[str, Any]:
    """DB上のジャンル情報を、実ファイル（ID3タグ等）に書き込む。"""
    with db_session() as session:
        service = GenreAppService(session)
        return serialize(service.apply_genres_to_files(track_ids))
