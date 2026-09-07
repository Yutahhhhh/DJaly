from typing import Any, Dict, List, Optional

from app.services.wordplay_app_service import WordplayAppService
from infra.database.connection import db_lock
from mcp_server.instance import db_session, mcp


@mcp.tool()
def list_wordplay_pairs(
    status: Optional[str] = None,
    from_track_id: Optional[int] = None,
    query: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
) -> Dict[str, Any]:
    """List persistent directional wordplay pairs and their source/target track metadata."""
    with db_session() as session:
        return WordplayAppService(session).list_pairs(
            status=status,
            from_track_id=from_track_id,
            query=query,
            limit=limit,
            offset=offset,
        )


@mcp.tool()
def propose_wordplay_pairs(pairs: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Persist 1-50 wordplay proposals atomically; new proposals start pending.

    For cue-drumming intros, use source_cue_mode="cue_drumming_intro", bracket the
    isolated source vocal with from_timestamp/source_cue_end_timestamp, and supply
    target_intro_timestamp plus target_landing_timestamp. ``to_timestamp`` remains
    an alias for the landing cue. The source must be a short, recognizable hit that
    works when tapped repeatedly, not a generic word inside a sentence. Require the
    same genre and prioritize the same subgenre, drum feel, era, and intro texture;
    reject genre-only phrase matches whose analyzed features clash. Keep actual BPM
    delta at or below 2%.
    """
    if not 1 <= len(pairs) <= 50:
        raise ValueError("pairs must contain between 1 and 50 items")
    with db_lock, db_session() as session:
        service = WordplayAppService(session)
        try:
            items = [service.propose_pair(commit=False, **pair) for pair in pairs]
            session.commit()
        except Exception:
            session.rollback()
            raise
        return {"items": items, "count": len(items)}


@mcp.tool()
def approve_wordplay_pair(pair_id: int) -> Dict[str, Any]:
    """Approve a boundary-fit pending pair without changing its verification status.

    Approval requires a usable source cue, an in-range target intro before its
    landing cue, compatible musical style, and no more than a 2% actual BPM delta.
    Cue-drumming may land at either the start or middle of the target track.
    """
    with db_session() as session:
        result = WordplayAppService(session).approve_pair(pair_id)
        if result is None:
            raise ValueError(f"Wordplay pair {pair_id} not found")
        return result


@mcp.tool()
def reject_wordplay_pair(pair_id: int) -> Dict[str, bool]:
    """Reject a proposal by physically deleting only the pair row."""
    with db_session() as session:
        if not WordplayAppService(session).delete_pair(pair_id):
            raise ValueError(f"Wordplay pair {pair_id} not found")
        return {"ok": True}
