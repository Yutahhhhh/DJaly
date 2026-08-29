"""Track search and detail tools for Rekordbox MCP."""

from __future__ import annotations

import asyncio
from typing import Any

from fastmcp import FastMCP

from rekordbox_mcp.domain.models import Track
from rekordbox_mcp.mcp.server import (
    get_mcp,
    get_playlist_manager,
    get_repository,
    require_db,
)

mcp: FastMCP = get_mcp()


def _track_summary(track: Track) -> dict[str, Any]:
    """Build the compact track summary returned by the search tools."""
    return {
        "id": track.id,
        "title": track.title,
        "artist": track.artist,
        "bpm": track.bpm,
        "key": track.key,
        "genre": track.genre,
    }


@mcp.tool(
    name="search_tracks",
    description="Search tracks by title/artist partial match with optional genre and BPM filters",
    tags={"track", "read"},
    annotations={"readOnlyHint": True},
)
@require_db
async def search_tracks(
    query: str,
    genre: str | None = None,
    min_bpm: float | None = None,
    max_bpm: float | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Search tracks by title/artist partial match with optional filters."""
    limit = max(1, min(limit, 100))
    repo = get_repository()
    filter: dict[str, Any] = {"query": query}
    if genre is not None:
        filter["genre"] = genre
    if min_bpm is not None:
        filter["min_bpm"] = min_bpm
    if max_bpm is not None:
        filter["max_bpm"] = max_bpm
    tracks = await asyncio.to_thread(repo.get_tracks, filter)
    return [_track_summary(t) for t in tracks[:limit]]


@mcp.tool(
    name="get_track",
    description="Get detailed track information by track ID",
    tags={"track", "read"},
    annotations={"readOnlyHint": True},
)
@require_db
async def get_track(track_id: int) -> dict[str, Any]:
    """Get a single track's details by ID."""
    repo = get_repository()
    track = await asyncio.to_thread(repo.get_track, track_id)
    if track is None:
        return {"success": False, "error": f"Track {track_id} not found"}
    return {
        "id": track.id,
        "title": track.title,
        "artist": track.artist,
        "bpm": track.bpm,
        "key": track.key,
        "genre": track.genre,
        "duration": round(track.duration_ms / 1000.0, 3),
    }


@mcp.tool(
    name="get_playlist_tracks_with_details",
    description="Get tracks in a playlist with full details, in playlist order",
    tags={"playlist", "track", "read"},
    annotations={"readOnlyHint": True},
)
@require_db
async def get_playlist_tracks_with_details(playlist_id: str) -> dict[str, Any]:
    """Get a playlist's tracks with details, preserving playlist order."""
    manager = get_playlist_manager()
    playlist = await asyncio.to_thread(manager.get_playlist, playlist_id)
    track_ids = await asyncio.to_thread(manager.get_tracks, playlist_id)

    repo = get_repository()
    all_tracks = await asyncio.to_thread(repo.get_tracks)
    by_id = {t.id: t for t in all_tracks}

    tracks = []
    for track_id in track_ids:
        track = by_id.get(track_id)
        if track is not None:
            tracks.append(_track_summary(track))

    return {
        "playlist_id": playlist_id,
        "playlist_name": playlist.name if playlist else None,
        "tracks": tracks,
    }
