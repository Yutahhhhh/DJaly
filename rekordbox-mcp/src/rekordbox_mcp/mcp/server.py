"""FastMCP Server for Rekordbox MCP."""

from __future__ import annotations

import argparse
import asyncio
import signal
import sys
from contextlib import asynccontextmanager
from typing import Any

from fastmcp import FastMCP

from rekordbox_mcp.config import Settings, get_settings
from rekordbox_mcp.db.connection import RekordboxConnection
from rekordbox_mcp.db.repository import RekordboxRepository
from rekordbox_mcp.domain.audit import AuditLogger
from rekordbox_mcp.domain.backup import BackupManager
from rekordbox_mcp.domain.changeset import ChangeSetManager
from rekordbox_mcp.domain.cue import CueManager
from rekordbox_mcp.domain.models import OperationMode
from rekordbox_mcp.domain.playlist import PlaylistManager
from rekordbox_mcp.domain.strategy import CueStrategy, create_cue_strategy

# Tool modules are imported lazily in create_mcp_server() to avoid circular imports

# Global service container
_services: dict[str, Any] = {}
_mcp: FastMCP | None = None

# Module-level mcp instance for direct import
mcp: FastMCP | None = None


def get_service(name: str) -> Any:
    """Get a service from the container."""
    return _services.get(name)


def set_service(name: str, service: Any) -> None:
    """Set a service in the container."""
    _services[name] = service


def get_repository() -> RekordboxRepository:
    """Get the repository instance."""
    repo = get_service("repository")
    if repo is None:
        raise RuntimeError("Repository not initialized. Call initialize_services() first.")
    return repo


def get_connection() -> RekordboxConnection:
    """Get the database connection."""
    conn = get_service("connection")
    if conn is None:
        raise RuntimeError("Connection not initialized. Call initialize_services() first.")
    return conn


def get_audit_logger() -> AuditLogger:
    """Get the audit logger."""
    logger = get_service("audit_logger")
    if logger is None:
        raise RuntimeError("Audit logger not initialized. Call initialize_services() first.")
    return logger


def get_backup_manager() -> BackupManager:
    """Get the backup manager."""
    manager = get_service("backup_manager")
    if manager is None:
        raise RuntimeError("Backup manager not initialized. Call initialize_services() first.")
    return manager


def get_changeset_manager() -> ChangeSetManager:
    """Get the changeset manager."""
    manager = get_service("changeset_manager")
    if manager is None:
        raise RuntimeError("ChangeSet manager not initialized. Call initialize_services() first.")
    return manager


def get_playlist_manager() -> PlaylistManager:
    """Get the playlist manager."""
    manager = get_service("playlist_manager")
    if manager is None:
        raise RuntimeError("Playlist manager not initialized. Call initialize_services() first.")
    return manager


def get_cue_strategy() -> CueStrategy:
    """Get the cue strategy."""
    strategy = get_service("cue_strategy")
    if strategy is None:
        raise RuntimeError("Cue strategy not initialized. Call initialize_services() first.")
    return strategy


def get_settings_instance() -> Settings:
    """Get the settings instance."""
    settings = get_service("settings")
    if settings is None:
        raise RuntimeError("Settings not initialized. Call initialize_services() first.")
    return settings


def ensure_initial_backup_if_needed() -> Any:
    """Create (or reuse) the protected full backup required before a write."""
    return get_backup_manager().ensure_initial_backup()


def initialize_services(
    settings: Settings | None = None,
    mode: OperationMode | str = OperationMode.READONLY,
) -> None:
    """Initialize all services."""
    global _services

    settings = settings or get_settings()
    mode = OperationMode(mode) if isinstance(mode, str) else mode

    # Update settings mode if provided
    if mode != settings.mode:
        settings.mode = mode

    # Create connection
    connection = RekordboxConnection(settings, mode)
    connection.connect()

    # Create repository
    repository = RekordboxRepository(settings, mode)

    # Create audit logger
    audit_logger = AuditLogger(settings)

    # Create backup manager
    backup_manager = BackupManager(db_accessor=connection, settings=settings)

    # Create playlist manager with repository adapter
    class RepositoryPlaylistAdapter:
        def __init__(self, repo: RekordboxRepository):
            self._repo = repo

        def get_all(self):
            return self._repo.get_playlists()

        def get_by_id(self, playlist_id: str):
            for p in self._repo.get_playlists():
                if p.id == playlist_id:
                    return p
            return None

        def get_children(self, parent_id: str):
            return [p for p in self._repo.get_playlists() if p.parent_id == parent_id]

        def save(self, playlist):
            # In masterdb mode, this would write to DB
            pass

        def delete(self, playlist_id: str):
            pass

        def get_tracks(self, playlist_id: str):
            return self._repo.get_playlist_tracks(playlist_id)

        def set_tracks(self, playlist_id: str, track_ids: list[int]):
            if mode == OperationMode.MASTERDB:
                self._repo.add_tracks_to_playlist(playlist_id, track_ids)

    playlist_manager = PlaylistManager(RepositoryPlaylistAdapter(repository))

    # Create changeset manager
    class ChangesetExecutor:
        def __init__(self, repo: RekordboxRepository, audit: AuditLogger):
            self._repo = repo
            self._audit = audit

        def execute(self, item):
            # Execute the change based on action type
            try:
                if item.action.value == "create":
                    if item.entity_type == "cue":
                        cue = item.new_data
                        self._repo.add_cue(cue["track_id"], cue)
                    elif item.entity_type == "playlist":
                        self._repo.create_playlist(item.new_data["name"], item.new_data.get("parent_id", "root"))
                elif item.action.value == "update":
                    if item.entity_type == "cue":
                        self._repo.update_cue(item.entity_id, item.new_data)
                    elif item.entity_type == "playlist":
                        # Handle playlist updates
                        pass
                elif item.action.value == "delete":
                    if item.entity_type == "cue":
                        self._repo.delete_cue(item.entity_id)
                return True
            except Exception:
                return False

        def revert(self, item):
            # Revert the change
            try:
                if item.action.value == "create":
                    if item.entity_type == "cue":
                        self._repo.delete_cue(item.entity_id)
                elif item.action.value == "delete":
                    if item.entity_type == "cue":
                        self._repo.add_cue(item.old_data["track_id"], item.old_data)
                elif item.action.value == "update":
                    if item.entity_type == "cue":
                        self._repo.update_cue(item.entity_id, item.old_data)
                return True
            except Exception:
                return False

    executor = ChangesetExecutor(repository, audit_logger)
    changeset_manager = ChangeSetManager(
        executor=executor,
        audit_logger=audit_logger,
        backup_manager=backup_manager,
        mode=mode,
    )

    # Create cue strategy
    cue_strategy = create_cue_strategy(
        profile_name=settings.cue_profile,
        memory_offset_bars=settings.cue_memory_offset_bars,
        loop_length_bars=settings.cue_loop_length_bars,
    )

    # Store services
    _services = {
        "settings": settings,
        "connection": connection,
        "repository": repository,
        "audit_logger": audit_logger,
        "backup_manager": backup_manager,
        "changeset_manager": changeset_manager,
        "playlist_manager": playlist_manager,
        "cue_strategy": cue_strategy,
    }


def cleanup_services() -> None:
    """Clean up all services."""
    global _services
    connection = _services.get("connection")
    if connection:
        connection.close()
    _services.clear()


def create_mcp_server() -> FastMCP:
    """Create and configure the FastMCP server."""
    global _mcp, mcp

    if _mcp is not None:
        return _mcp

    # Publish the instance before importing tool modules.  Their module-level
    # decorators call get_mcp(); if the instance is not published yet,
    # get_mcp() recursively calls create_mcp_server() and the decorators can
    # end up attached to a different (or incomplete) FastMCP instance.
    server = FastMCP(
        "Rekordbox MCP Server",
        instructions="""
Rekordbox MCP Server - Manage your Rekordbox library via MCP.

Operation Modes:
- readonly: Read-only access to tracks, cues, playlists (default)
- xml: Export cues to Rekordbox collection XML (Automark-for-Rekordbox compatible)
- masterdb: Direct database writes (requires Rekordbox to be closed)

Available Tools:
- Cue Management: get_cues, add_hot_cue, add_memory_cue, add_loop, update_cue, delete_cue, snap_to_beatgrid, generate_cues, get_cue_profiles, set_cue_profile
- Playlist Management: list_playlists, get_playlist_tracks, create_playlist, create_folder, rename_playlist, move_playlist, delete_playlist, add_tracks_to_playlist, remove_track_from_playlist, move_track_in_playlist, copy_track_in_playlist, reorder_playlist, replace_playlist_tracks, dedupe_playlist, process_playlist_cues
- ChangeSet Management: create_changeset, preview_changeset, apply_changeset, undo_changeset, rollback_changeset, get_audit_log
- Backup Management: backup_now, list_backups, protect_backup, restore_backup, cleanup_backups, get_backup_usage
- Mode Management: set_mode, get_mode, get_status

All write operations require masterdb mode and Rekordbox to be closed.
        """,
    )
    _mcp = server
    mcp = server

    # Import tool modules to register tools (lazy import to avoid circular deps)
    from rekordbox_mcp.mcp import tools_backup, tools_changeset, tools_cue, tools_mode, tools_playlist  # noqa: F401

    return server


def get_mcp() -> FastMCP:
    """Get the MCP server instance."""
    global _mcp, mcp
    if _mcp is None:
        _mcp = create_mcp_server()
        mcp = _mcp
    return _mcp


async def run_server(
    database_path: str | None = None,
    mode: str = "readonly",
    db_key: str | None = None,
    db_dir: str | None = None,
) -> None:
    """Run the MCP server with stdio transport."""
    # Parse mode
    try:
        operation_mode = OperationMode(mode)
    except ValueError:
        print(f"Invalid mode: {mode}. Must be one of: readonly, xml, masterdb", file=sys.stderr)
        sys.exit(1)

    # Override settings with CLI args
    settings = get_settings()
    if database_path:
        settings.db_path = database_path
    if db_key:
        settings.db_key = db_key
    if db_dir:
        settings.db_dir = db_dir

    # Initialize services
    initialize_services(settings, operation_mode)

    # Setup signal handlers
    loop = asyncio.get_running_loop()

    def signal_handler():
        print("Shutting down...", file=sys.stderr)
        cleanup_services()
        loop.stop()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, signal_handler)
        except NotImplementedError:
            # Windows doesn't support add_signal_handler
            pass

    # Get MCP server and run
    mcp = get_mcp()
    await mcp.run_stdio_async()


def main() -> None:
    """Main entry point for the MCP server."""
    parser = argparse.ArgumentParser(description="Rekordbox MCP Server")
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
        "--version",
        action="version",
        version="Rekordbox MCP Server 1.0.0",
    )

    args = parser.parse_args()

    try:
        asyncio.run(run_server(
            database_path=args.database_path,
            mode=args.mode,
            db_key=args.db_key,
            db_dir=args.db_dir,
        ))
    except KeyboardInterrupt:
        pass
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
