from fastapi import APIRouter
from typing import Any, Dict, List

from mcp_server.instance import mcp
from mcp_server.server import MCP_HTTP_PATH
from config import settings

router = APIRouter()


@router.get("/api/mcp/info")
async def get_mcp_info() -> Dict[str, Any]:
    """MCP サーバーの接続情報とツール一覧を返す (設定ページ用)。"""
    tools = await mcp.list_tools()
    tool_list: List[Dict[str, Any]] = [
        {"name": t.name, "description": t.description or ""} for t in tools
    ]
    tool_list.sort(key=lambda t: t["name"])
    return {
        "server_name": mcp.name,
        "port": settings.PLUMDECK_PORT,
        "http_path": MCP_HTTP_PATH,
        "url": f"http://127.0.0.1:{settings.PLUMDECK_PORT}{MCP_HTTP_PATH}",
        "tool_count": len(tool_list),
        "tools": tool_list,
    }
