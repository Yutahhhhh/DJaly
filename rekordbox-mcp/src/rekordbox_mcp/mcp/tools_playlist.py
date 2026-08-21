"""Playlist management tools for Rekordbox MCP."""

from __future__ import annotations

import asyncio
from typing import Any, Literal

from fastmcp import FastMCP

from rekordbox_mcp.domain.models import OperationMode, Playlist
from rekordbox_mcp.mcp.server import (
    get_mcp,
    get_playlist_manager,
    get_repository,
    get_settings_instance,
    ensure_initial_backup_if_needed,
)

mcp: FastMCP = get_mcp()


def _check_write_mode() -> OperationMode:
    """Check if we're in a write mode and Rekordbox is not running."""
    settings = get_settings_instance()
    mode = settings.mode
    if mode == OperationMode.READONLY:
        raise RuntimeError("Write operations require masterdb or xml mode. Use set_mode to change mode.")
    if mode == OperationMode.MASTERDB:
        from rekordbox_mcp.mcp.server import get_connection
        conn = get_connection()
        if conn.is_rekordbox_running():
            raise RuntimeError("Rekordbox is running. Close Rekordbox before write operations.")
    ensure_initial_backup_if_needed()
    return mode


@mcp.tool(
    name="list_playlists",
    description="List all playlists and folders",
    tags={"playlist", "read"},
    annotations={"readOnlyHint": True},
)
async def list_playlists() -> dict[str, Any]:
    """List all playlists and folders."""
    manager = get_playlist_manager()
    playlists = await asyncio.to_thread(manager.get_all_playlists)
    return {
        "playlists": [p.model_dump(mode="json") for p in playlists],
        "count": len(playlists),
    }


@mcp.tool(
    name="get_playlist_tracks",
    description="Get tracks in a playlist",
    tags={"playlist", "read"},
    annotations={"readOnlyHint": True},
)
async def get_playlist_tracks(playlist_id: str) -> dict[str, Any]:
    """Get track IDs in a playlist in order."""
    manager = get_playlist_manager()
    track_ids = await asyncio.to_thread(manager.get_tracks, playlist_id)
    playlist = await asyncio.to_thread(manager.get_playlist, playlist_id)
    return {
        "playlist_id": playlist_id,
        "playlist_name": playlist.name if playlist else None,
        "track_ids": track_ids,
        "count": len(track_ids),
    }


@mcp.tool(
    name="create_playlist",
    description="Create a new playlist",
    tags={"playlist", "write"},
    annotations={"readOnlyHint": False, "destructiveHint": False},
)
async def create_playlist(name: str, parent_id: str = "root") -> dict[str, Any]:
    """Create a new regular playlist."""
    _check_write_mode()

    manager = get_playlist_manager()
    playlist = await asyncio.to_thread(manager.create_playlist, name, parent_id)
    return {"success": True, "playlist": playlist.model_dump(mode="json")}


@mcp.tool(
    name="create_folder",
    description="Create a new folder",
    tags={"playlist", "write"},
    annotations={"readOnlyHint": False, "destructiveHint": False},
)
async def create_folder(name: str, parent_id: str = "root") -> dict[str, Any]:
    """Create a new folder."""
    _check_write_mode()

    manager = get_playlist_manager()
    folder = await asyncio.to_thread(manager.create_folder, name, parent_id)
    return {"success": True, "playlist": folder.model_dump(mode="json")}


@mcp.tool(
    name="rename_playlist",
    description="Rename a playlist or folder",
    tags={"playlist", "write"},
    annotations={"readOnlyHint": False, "destructiveHint": False},
)
async def rename_playlist(playlist_id: str, new_name: str) -> dict[str, Any]:
    """Rename a playlist or folder."""
    _check_write_mode()

    manager = get_playlist_manager()
    playlist = await asyncio.to_thread(manager.rename_playlist, playlist_id, new_name)
    if not playlist:
        return {"success": False, "error": f"Playlist {playlist_id} not found"}
    return {"success": True, "playlist": playlist.model_dump(mode="json")}


@mcp.tool(
    name="move_playlist",
    description="Move a playlist or folder to a different parent",
    tags={"playlist", "write"},
    annotations={"readOnlyHint": False, "destructiveHint": False},
)
async def move_playlist(playlist_id: str, new_parent_id: str, seq: int | None = None) -> dict[str, Any]:
    """Move a playlist or folder to a different parent."""
    _check_write_mode()

    manager = get_playlist_manager()
    try:
        playlist = await asyncio.to_thread(manager.move_playlist, playlist_id, new_parent_id, seq)
        if not playlist:
            return {"success": False, "error": f"Playlist {playlist_id} not found"}
        return {"success": True, "playlist": playlist.model_dump(mode="json")}
    except ValueError as e:
        return {"success": False, "error": str(e)}


@mcp.tool(
    name="delete_playlist",
    description="Delete a playlist or folder",
    tags={"playlist", "write"},
    annotations={"readOnlyHint": False, "destructiveHint": True},
)
async def delete_playlist(playlist_id: str, recursive: bool = False) -> dict[str, Any]:
    """Delete a playlist or folder. If recursive, also delete children."""
    _check_write_mode()

    manager = get_playlist_manager()
    try:
        success = await asyncio.to_thread(manager.delete_playlist, playlist_id, recursive)
        return {"success": success, "playlist_id": playlist_id}
    except ValueError as e:
        return {"success": False, "error": str(e)}


@mcp.tool(
    name="add_tracks_to_playlist",
    description="Add tracks to a playlist",
    tags={"playlist", "write"},
    annotations={"readOnlyHint": False, "destructiveHint": False},
)
async def add_tracks_to_playlist(playlist_id: str, track_ids: list[int], position: int | None = None) -> dict[str, Any]:
    """Add tracks to a playlist."""
    _check_write_mode()

    manager = get_playlist_manager()
    playlist = await asyncio.to_thread(manager.add_tracks, playlist_id, track_ids, position)
    if not playlist:
        return {"success": False, "error": f"Playlist {playlist_id} not found or is a folder/smart playlist"}
    return {"success": True, "playlist": playlist.model_dump(mode="json"), "added_count": len(track_ids)}


@mcp.tool(
    name="remove_track_from_playlist",
    description="Remove a track from a playlist",
    tags={"playlist", "write"},
    annotations={"readOnlyHint": False, "destructiveHint": True},
)
async def remove_track_from_playlist(playlist_id: str, track_id: int) -> dict[str, Any]:
    """Remove a track from a playlist (first occurrence)."""
    _check_write_mode()

    manager = get_playlist_manager()
    playlist = await asyncio.to_thread(manager.remove_track, playlist_id, track_id)
    if not playlist:
        return {"success": False, "error": f"Playlist {playlist_id} not found or track not in playlist"}
    return {"success": True, "playlist": playlist.model_dump(mode="json")}


@mcp.tool(
    name="move_track_in_playlist",
    description="Move a track within a playlist",
    tags={"playlist", "write"},
    annotations={"readOnlyHint": False, "destructiveHint": False},
)
async def move_track_in_playlist(playlist_id: str, from_index: int, to_index: int) -> dict[str, Any]:
    """Move a track within a playlist."""
    _check_write_mode()

    manager = get_playlist_manager()
    playlist = await asyncio.to_thread(manager.move_track, playlist_id, from_index, to_index)
    if not playlist:
        return {"success": False, "error": f"Playlist {playlist_id} not found or invalid indices"}
    return {"success": True, "playlist": playlist.model_dump(mode="json")}


@mcp.tool(
    name="copy_track_in_playlist",
    description="Copy a track to a position in a playlist (adds duplicate)",
    tags={"playlist", "write"},
    annotations={"readOnlyHint": False, "destructiveHint": False},
)
async def copy_track_in_playlist(playlist_id: str, track_id: int, position: int | None = None) -> dict[str, Any]:
    """Copy a track to a position in a playlist (adds duplicate)."""
    _check_write_mode()

    manager = get_playlist_manager()
    playlist = await asyncio.to_thread(manager.copy_track, playlist_id, track_id, position)
    if not playlist:
        return {"success": False, "error": f"Playlist {playlist_id} not found or track not in playlist"}
    return {"success": True, "playlist": playlist.model_dump(mode="json")}


@mcp.tool(
    name="reorder_playlist",
    description="Reorder tracks in a playlist to match given order",
    tags={"playlist", "write"},
    annotations={"readOnlyHint": False, "destructiveHint": False},
)
async def reorder_playlist(playlist_id: str, track_ids: list[int]) -> dict[str, Any]:
    """Reorder tracks to match the given order (must contain all current tracks)."""
    _check_write_mode()

    manager = get_playlist_manager()
    try:
        playlist = await asyncio.to_thread(manager.reorder, playlist_id, track_ids)
        if not playlist:
            return {"success": False, "error": f"Playlist {playlist_id} not found"}
        return {"success": True, "playlist": playlist.model_dump(mode="json")}
    except ValueError as e:
        return {"success": False, "error": str(e)}


@mcp.tool(
    name="replace_playlist_tracks",
    description="Replace all tracks in a playlist",
    tags={"playlist", "write"},
    annotations={"readOnlyHint": False, "destructiveHint": False},
)
async def replace_playlist_tracks(playlist_id: str, track_ids: list[int]) -> dict[str, Any]:
    """Replace all tracks in a playlist."""
    _check_write_mode()

    manager = get_playlist_manager()
    playlist = await asyncio.to_thread(manager.replace_tracks, playlist_id, track_ids)
    if not playlist:
        return {"success": False, "error": f"Playlist {playlist_id} not found or is a folder/smart playlist"}
    return {"success": True, "playlist": playlist.model_dump(mode="json"), "track_count": len(track_ids)}


@mcp.tool(
    name="dedupe_playlist",
    description="Remove duplicate tracks from a playlist",
    tags={"playlist", "write"},
    annotations={"readOnlyHint": False, "destructiveHint": False},
)
async def dedupe_playlist(playlist_id: str, keep: Literal["first", "last"] = "first") -> dict[str, Any]:
    """Remove duplicate tracks from a playlist."""
    _check_write_mode()

    manager = get_playlist_manager()
    playlist = await asyncio.to_thread(manager.dedupe, playlist_id, keep)
    if not playlist:
        return {"success": False, "error": f"Playlist {playlist_id} not found or is a folder/smart playlist"}
    return {"success": True, "playlist": playlist.model_dump(mode="json")}


@mcp.tool(
    name="process_playlist_cues",
    description="Generate cues for all tracks in a playlist",
    tags={"playlist", "cue", "write"},
    annotations={"readOnlyHint": False, "destructiveHint": False},
)
async def process_playlist_cues(playlist_id: str, mode: Literal["replace", "merge", "preserve"] = "replace") -> dict[str, Any]:
    """Generate cues for all tracks in a playlist using the cue strategy."""
    _check_write_mode()

    manager = get_playlist_manager()
    track_ids = await asyncio.to_thread(manager.get_tracks, playlist_id)

    if not track_ids:
        return {"success": True, "message": "Playlist is empty", "results": {}}

    from rekordbox_mcp.mcp.server import get_cue_strategy
    strategy = get_cue_strategy()
    repo = get_repository()

    results = {}
    for track_id in track_ids:
        try:
            track = await asyncio.to_thread(repo.get_track, track_id)
            if not track or not track.beat_grid:
                results[track_id] = {"success": False, "error": "Track not found or no beat grid"}
                continue

            proposal = await asyncio.to_thread(strategy.propose, track)
            existing_cues = await asyncio.to_thread(repo.get_cues, track_id)
            from rekordbox_mcp.domain.beatgrid import BeatGrid as BeatGridDomain
            from rekordbox_mcp.domain.cue import CueManager
            cue_manager = CueManager(track_id, BeatGridDomain.from_model(track.beat_grid), existing_cues)

            new_cues = await asyncio.to_thread(
                cue_manager.generate_cues_from_profile,
                profile=strategy.profile,
                strategy_proposal=proposal,
                mode=mode,
            )

            # ``CueManager`` only builds the replacement set; remove persisted
            # cues here before adding the newly generated ones.
            if mode == "replace":
                for cue in existing_cues:
                    await asyncio.to_thread(repo.delete_cue, cue.id)

            saved = []
            if get_settings_instance().mode == OperationMode.XML:
                from rekordbox_mcp.mcp.tools_cue import _persist_cues
                saved_cues = await asyncio.to_thread(_persist_cues, track, new_cues, OperationMode.XML)
            else:
                saved_cues = [await asyncio.to_thread(repo.add_cue, track_id, cue) for cue in new_cues]
            for saved_cue in saved_cues:
                saved.append(saved_cue.model_dump(mode="json"))

            results[track_id] = {
                "success": True,
                "generated": len(saved),
                "cues": saved,
                "confidence": proposal.confidence,
            }
        except Exception as e:
            results[track_id] = {"success": False, "error": str(e)}

    return {"success": True, "playlist_id": playlist_id, "results": results}
