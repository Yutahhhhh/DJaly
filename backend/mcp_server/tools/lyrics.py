from typing import Any, Dict, Optional

from mcp_server.instance import mcp, db_session, serialize


@mcp.tool()
def get_track_lyrics(track_id: int) -> Dict[str, Any]:
    """指定した楽曲の歌詞（LRC形式含む）を取得する。"""
    from domain.models.lyrics import Lyrics

    with db_session() as session:
        lyrics = session.get(Lyrics, track_id)
        if not lyrics:
            raise ValueError(f"Lyrics not found for track {track_id}")
        return serialize(lyrics)


@mcp.tool()
def analyze_track_wordplay(track_id: int, force: bool = False) -> Dict[str, Any]:
    """歌詞からDJワードプレイ（曲を繋ぐキーワード）候補をLLMで抽出する。結果はキャッシュされ、2回目以降は force=True 時のみ再解析する。"""
    from api.routers.lyrics import analyze_lyrics

    with db_session() as session:
        return {"keywords": serialize(analyze_lyrics(track_id, force, session))}


@mcp.tool()
def search_lyrics(q: str, exclude_track_id: Optional[int] = None) -> Dict[str, Any]:
    """歌詞本文をキーワードで横断検索し、一致箇所のスニペットと楽曲を返す（3文字以上のクエリが必要）。"""
    from api.routers.lyrics import search_lyrics as _search_lyrics

    with db_session() as session:
        return {"results": serialize(_search_lyrics(q, exclude_track_id, session))}


@mcp.tool()
def find_wordplay_links(track_id: int, limit: int = 20) -> Dict[str, Any]:
    """指定曲の歌詞からワードプレイキーワードを解析し、各キーワードを含む他曲を繋ぎ候補として返す。"""
    from api.routers.lyrics import analyze_lyrics, search_lyrics as _search_lyrics

    with db_session() as session:
        keywords = analyze_lyrics(track_id, False, session)
        links = []
        for kw in keywords:
            results = _search_lyrics(kw["keyword"], exclude_track_id=track_id, session=session)
            for r in results[:limit]:
                links.append({
                    "keyword": kw["keyword"],
                    "count": kw["count"],
                    "track": r["track"],
                    "snippet": r["snippet"],
                    "matched_text": r["matched_text"],
                    "timestamp": r["timestamp"],
                })
        return {"track_id": track_id, "keywords": keywords, "links": links}
