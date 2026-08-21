"""FastAPI application for Rekordbox Web API."""

from __future__ import annotations

import argparse
import sys

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from rekordbox_mcp.config import get_settings
from rekordbox_mcp.domain.models import OperationMode
from rekordbox_mcp.mcp.server import initialize_services
from rekordbox_mcp.webapi.routers import backups, changesets, cues, playlists, system, tracks


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title="Rekordbox Web API",
        description="REST API for managing your Rekordbox library (cues, playlists, changesets, backups).",
        version="1.0.0",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(tracks.router)
    app.include_router(cues.router)
    app.include_router(playlists.router)
    app.include_router(changesets.router)
    app.include_router(backups.router)
    app.include_router(system.router)

    return app


app = create_app()


def main() -> None:
    """Main entry point for the Web API server."""
    parser = argparse.ArgumentParser(description="Rekordbox Web API Server")
    parser.add_argument(
        "--database-path",
        "-d",
        type=str,
        help="Path to rekordbox master.db (auto-detected if not set)",
    )
    parser.add_argument(
        "--mode",
        "-m",
        type=str,
        choices=["readonly", "xml", "masterdb"],
        default="readonly",
        help="Operation mode (default: readonly)",
    )
    parser.add_argument(
        "--db-key",
        type=str,
        help="Database encryption key (auto-extracted if not set)",
    )
    parser.add_argument(
        "--db-dir",
        type=str,
        help="Rekordbox database directory (for ANLZ files, auto-detected if not set)",
    )
    parser.add_argument(
        "--host",
        type=str,
        help="Web API host (defaults to config webapi_host)",
    )
    parser.add_argument(
        "--port",
        type=int,
        help="Web API port (defaults to config webapi_port)",
    )
    parser.add_argument(
        "--version",
        action="version",
        version="Rekordbox Web API Server 1.0.0",
    )

    args = parser.parse_args()

    try:
        operation_mode = OperationMode(args.mode)
    except ValueError:
        print(f"Invalid mode: {args.mode}. Must be one of: readonly, xml, masterdb", file=sys.stderr)
        sys.exit(1)

    settings = get_settings()
    if args.database_path:
        settings.db_path = args.database_path
    if args.db_key:
        settings.db_key = args.db_key
    if args.db_dir:
        settings.db_dir = args.db_dir

    initialize_services(settings, operation_mode)

    host = args.host or settings.webapi_host
    port = args.port or settings.webapi_port

    try:
        import uvicorn

        uvicorn.run(app, host=host, port=port)
    except KeyboardInterrupt:
        pass
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
