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
        "resolve natural-language 'vibe' descriptions into audio-feature filters, "
        "manage setlists (create/reorder/auto-generate/bridge/export), run AI genre "
        "analysis, and inspect lyrics/wordplay. Prefer search_tracks/vibe_search "
        "before assuming a track exists; track ids returned by these tools are "
        "required by setlist and genre tools."
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
