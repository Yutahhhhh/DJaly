"""Playlist management REST API."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from rekordbox_mcp.mcp.server import get_cue_strategy, get_playlist_manager, get_repository
from rekordbox_mcp.webapi.deps import check_write_mode

router = APIRouter(prefix="/api/playlists", tags=["playlists"])


class CreatePlaylistRequest(BaseModel):
    name: str
    parent_id: str = "root"


class RenamePlaylistRequest(BaseModel):
    new_name: str


class AddTracksRequest(BaseModel):
    track_ids: list[int]
    position: int | None = None


class ReorderRequest(BaseModel):
    track_ids: list[int]


class ReplaceTracksRequest(BaseModel):
    track_ids: list[int]


class DedupeRequest(BaseModel):
    keep: Literal["first", "last"] = "first"


class ProcessCuesRequest(BaseModel):
    mode: Literal["replace", "merge", "preserve"] = "replace"


@router.get("")
async def list_playlists() -> dict[str, Any]:
    """List all playlists and folders."""
    manager = get_playlist_manager()
    playlists = manager.get_all_playlists()
    return {
        "playlists": [p.model_dump(mode="json") for p in playlists],
        "count": len(playlists),
    }


@router.get("/{playlist_id}/tracks")
async def get_playlist_tracks(playlist_id: str) -> dict[str, Any]:
    """Get track IDs in a playlist in order."""
    manager = get_playlist_manager()
    track_ids = manager.get_tracks(playlist_id)
    playlist = manager.get_playlist(playlist_id)
    return {
        "playlist_id": playlist_id,
        "playlist_name": playlist.name if playlist else None,
        "track_ids": track_ids,
        "count": len(track_ids),
    }


@router.post("")
async def create_playlist(body: CreatePlaylistRequest) -> dict[str, Any]:
    """Create a new regular playlist."""
    check_write_mode()

    manager = get_playlist_manager()
    playlist = manager.create_playlist(body.name, body.parent_id)
    return {"success": True, "playlist": playlist.model_dump(mode="json")}


@router.post("/folder")
async def create_folder(body: CreatePlaylistRequest) -> dict[str, Any]:
    """Create a new folder."""
    check_write_mode()

    manager = get_playlist_manager()
    folder = manager.create_folder(body.name, body.parent_id)
    return {"success": True, "playlist": folder.model_dump(mode="json")}


@router.put("/{playlist_id}")
async def rename_playlist(playlist_id: str, body: RenamePlaylistRequest) -> dict[str, Any]:
    """Rename a playlist or folder."""
    check_write_mode()

    manager = get_playlist_manager()
    playlist = manager.rename_playlist(playlist_id, body.new_name)
    if not playlist:
        raise HTTPException(status_code=404, detail=f"Playlist {playlist_id} not found")
    return {"success": True, "playlist": playlist.model_dump(mode="json")}


@router.delete("/{playlist_id}")
async def delete_playlist(playlist_id: str, recursive: bool = False) -> dict[str, Any]:
    """Delete a playlist or folder. If recursive, also delete children."""
    check_write_mode()

    manager = get_playlist_manager()
    try:
        success = manager.delete_playlist(playlist_id, recursive)
        return {"success": success, "playlist_id": playlist_id}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/{playlist_id}/tracks")
async def add_tracks_to_playlist(playlist_id: str, body: AddTracksRequest) -> dict[str, Any]:
    """Add tracks to a playlist."""
    check_write_mode()

    manager = get_playlist_manager()
    playlist = manager.add_tracks(playlist_id, body.track_ids, body.position)
    if not playlist:
        raise HTTPException(status_code=404, detail=f"Playlist {playlist_id} not found or is a folder/smart playlist")
    return {"success": True, "playlist": playlist.model_dump(mode="json"), "added_count": len(body.track_ids)}


@router.delete("/{playlist_id}/tracks/{track_id}")
async def remove_track_from_playlist(playlist_id: str, track_id: int) -> dict[str, Any]:
    """Remove a track from a playlist (first occurrence)."""
    check_write_mode()

    manager = get_playlist_manager()
    playlist = manager.remove_track(playlist_id, track_id)
    if not playlist:
        raise HTTPException(status_code=404, detail=f"Playlist {playlist_id} not found or track not in playlist")
    return {"success": True, "playlist": playlist.model_dump(mode="json")}


@router.post("/{playlist_id}/reorder")
async def reorder_playlist(playlist_id: str, body: ReorderRequest) -> dict[str, Any]:
    """Reorder tracks to match the given order (must contain all current tracks)."""
    check_write_mode()

    manager = get_playlist_manager()
    try:
        playlist = manager.reorder(playlist_id, body.track_ids)
        if not playlist:
            raise HTTPException(status_code=404, detail=f"Playlist {playlist_id} not found")
        return {"success": True, "playlist": playlist.model_dump(mode="json")}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/{playlist_id}/replace")
async def replace_playlist_tracks(playlist_id: str, body: ReplaceTracksRequest) -> dict[str, Any]:
    """Replace all tracks in a playlist."""
    check_write_mode()

    manager = get_playlist_manager()
    playlist = manager.replace_tracks(playlist_id, body.track_ids)
    if not playlist:
        raise HTTPException(status_code=404, detail=f"Playlist {playlist_id} not found or is a folder/smart playlist")
    return {"success": True, "playlist": playlist.model_dump(mode="json"), "track_count": len(body.track_ids)}


@router.post("/{playlist_id}/dedupe")
async def dedupe_playlist(playlist_id: str, body: DedupeRequest) -> dict[str, Any]:
    """Remove duplicate tracks from a playlist."""
    check_write_mode()

    manager = get_playlist_manager()
    playlist = manager.dedupe(playlist_id, body.keep)
    if not playlist:
        raise HTTPException(status_code=404, detail=f"Playlist {playlist_id} not found or is a folder/smart playlist")
    return {"success": True, "playlist": playlist.model_dump(mode="json")}


@router.post("/{playlist_id}/process-cues")
async def process_playlist_cues(playlist_id: str, body: ProcessCuesRequest) -> dict[str, Any]:
    """Generate cues for all tracks in a playlist using the cue strategy."""
    check_write_mode()

    manager = get_playlist_manager()
    track_ids = manager.get_tracks(playlist_id)

    if not track_ids:
        return {"success": True, "message": "Playlist is empty", "results": {}}

    strategy = get_cue_strategy()
    repo = get_repository()

    from rekordbox_mcp.domain.cue import CueManager

    results = {}
    for track_id in track_ids:
        try:
            track = repo.get_track(track_id)
            if not track or not track.beat_grid:
                results[track_id] = {"success": False, "error": "Track not found or no beat grid"}
                continue

            proposal = strategy.propose(track)
            existing_cues = repo.get_cues(track_id)
            cue_manager = CueManager(track_id, track.beat_grid, existing_cues)

            new_cues = cue_manager.generate_cues_from_profile(
                profile=strategy.profile,
                strategy_proposal=proposal,
                mode=body.mode,
            )

            saved = []
            for cue in new_cues:
                saved_cue = repo.add_cue(track_id, cue)
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
