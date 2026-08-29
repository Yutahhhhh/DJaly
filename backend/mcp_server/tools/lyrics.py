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
def search_lyrics(q: str, exclude_track_id: Optional[int] = None) -> Dict[str, Any]:
    """歌詞本文をキーワードで横断検索し、一致箇所のスニペットと楽曲を返す（3文字以上のクエリが必要）。"""
    from api.routers.lyrics import search_lyrics as _search_lyrics

    with db_session() as session:
        return {"results": serialize(_search_lyrics(q, exclude_track_id, session))}


@mcp.tool()
def find_wordplay_links(track_id: int, keywords: list[str], limit: int = 20) -> Dict[str, Any]:
    """MCPクライアント側LLMが歌詞から選んだキーワードを使い、他曲の一致箇所を検索する。
    先に get_track_lyrics を呼び、1〜3語の特徴的なフレーズを keywords に渡すこと。
    """
    from api.routers.lyrics import search_lyrics as _search_lyrics

    with db_session() as session:
        links = []
        normalized_keywords = []
        for keyword in keywords:
            keyword = keyword.strip()
            if len(keyword) < 3 or keyword.lower() in {k.lower() for k in normalized_keywords}:
                continue
            normalized_keywords.append(keyword)
            results = _search_lyrics(keyword, exclude_track_id=track_id, session=session)
            for r in results[:limit]:
                links.append({
                    "keyword": keyword,
                    "track": r["track"],
                    "snippet": r["snippet"],
                    "matched_text": r["matched_text"],
                    "timestamp": r["timestamp"],
                })
        return {"track_id": track_id, "keywords": normalized_keywords, "links": links}
