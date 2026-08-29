from contextlib import contextmanager
from typing import Any, Dict, Iterator, List

from sqlmodel import Session
from mcp.server.mcpserver import MCPServer

from infra.database import connection

mcp = MCPServer(
    name="Djaly",
    title="Djaly Music Library",
    instructions=(
        "Djaly is a local-first DJ music library. Use these tools to search tracks, "
        "manage setlists, classify genres, and inspect lyrics/wordplay. You are the "
        "reasoning model: Djaly never calls a separate LLM. Translate natural-language "
        "vibes into search/setlist tool parameters yourself. For genre work, call "
        "get_genre_analysis_context, classify the returned tracks, then call "
        "apply_genre_analysis or apply_genre_analyses. For wordplay, inspect lyrics, "
        "choose phrases yourself, then call find_wordplay_links. Prefer search_tracks "
        "before assuming a track exists; returned track ids are required by mutation tools."
    ),
)


@contextmanager
def db_session() -> Iterator[Session]:
    with Session(connection.engine) as session:
        yield session


def serialize(obj: Any) -> Any:
    """SQLModel/pydantic インスタンスを JSON-safe な dict に変換する（datetime は ISO 文字列化）。"""
    if isinstance(obj, list):
        return [serialize(o) for o in obj]
    if isinstance(obj, dict):
        return {k: serialize(v) for k, v in obj.items()}
    if hasattr(obj, "model_dump"):
        return serialize(obj.model_dump(mode="json"))
    return obj


def track_list_payload(tracks: List[Any]) -> Dict[str, Any]:
    items = serialize(tracks)
    return {"count": len(items), "tracks": items}
