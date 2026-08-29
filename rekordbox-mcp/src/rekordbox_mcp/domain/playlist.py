"""Playlist domain logic - CRUD operations for playlists and folders."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol
from uuid import uuid4

from rekordbox_mcp.domain.models import Playlist


class PlaylistRepository(Protocol):
    """Protocol for playlist data access."""

    def get_all(self) -> list[Playlist]: ...
    def get_by_id(self, playlist_id: str) -> Playlist | None: ...
    def get_children(self, parent_id: str) -> list[Playlist]: ...
    def save(self, playlist: Playlist) -> Playlist | None: ...
    def delete(self, playlist_id: str) -> None: ...
    def get_tracks(self, playlist_id: str) -> list[int]: ...
    def set_tracks(self, playlist_id: str, track_ids: list[int]) -> None: ...


class PlaylistManager:
    """Manages playlist and folder operations."""

    def __init__(self, repository: PlaylistRepository | None = None):
        self._repository = repository
        self._playlists: dict[str, Playlist] = {}
        self._initialized = False

    def _ensure_initialized(self) -> None:
        """Load playlists from repository if available."""
        if self._initialized or self._repository is None:
            return
        for playlist in self._repository.get_all():
            self._playlists[playlist.id] = playlist
        self._initialized = True

    def _get_playlist(self, playlist_id: str) -> Playlist | None:
        self._ensure_initialized()
        return self._playlists.get(playlist_id)

    def _save_playlist(self, playlist: Playlist) -> Playlist:
        playlist.updated_at = datetime.now()
        if self._repository:
            saved = self._repository.save(playlist)
            if saved is not None and saved.id != playlist.id:
                # master.db stores playlist IDs as integers; the repository
                # may have replaced the UUID placeholder with a real ID.
                self._playlists.pop(playlist.id, None)
                playlist.id = saved.id
        self._playlists[playlist.id] = playlist
        return playlist

    def _delete_playlist(self, playlist_id: str) -> None:
        if playlist_id in self._playlists:
            del self._playlists[playlist_id]
        if self._repository:
            self._repository.delete(playlist_id)

    def _get_next_seq(self, parent_id: str) -> int:
        self._ensure_initialized()
        children = [p for p in self._playlists.values() if p.parent_id == parent_id]
        return max((p.seq for p in children), default=-1) + 1

    # =========================================================================
    # Playlist/Folder Creation
    # =========================================================================

    def create_playlist(
        self,
        name: str,
        parent_id: str = "root",
        seq: int | None = None,
    ) -> Playlist:
        """Create a new regular playlist."""
        self._ensure_initialized()
        playlist = Playlist(
            id=str(uuid4()),
            name=name,
            parent_id=parent_id,
            seq=seq if seq is not None else self._get_next_seq(parent_id),
            attribute=0,  # regular playlist
            track_ids=[],
        )
        self._save_playlist(playlist)
        return playlist

    def create_folder(
        self,
        name: str,
        parent_id: str = "root",
        seq: int | None = None,
    ) -> Playlist:
        """Create a new folder."""
        self._ensure_initialized()
        folder = Playlist(
            id=str(uuid4()),
            name=name,
            parent_id=parent_id,
            seq=seq if seq is not None else self._get_next_seq(parent_id),
            attribute=1,  # folder
            track_ids=[],
        )
        self._save_playlist(folder)
        return folder

    def create_smart_playlist(
        self,
        name: str,
        smart_list_xml: str,
        parent_id: str = "root",
        seq: int | None = None,
    ) -> Playlist:
        """Create a new smart playlist."""
        self._ensure_initialized()
        playlist = Playlist(
            id=str(uuid4()),
            name=name,
            parent_id=parent_id,
            seq=seq if seq is not None else self._get_next_seq(parent_id),
            attribute=2,  # smart playlist
            smart_list_xml=smart_list_xml,
            track_ids=[],
        )
        self._save_playlist(playlist)
        return playlist

    # =========================================================================
    # Playlist/Folder Modification
    # =========================================================================

    def rename_playlist(self, playlist_id: str, new_name: str) -> Playlist | None:
        """Rename a playlist or folder."""
        playlist = self._get_playlist(playlist_id)
        if not playlist:
            return None
        playlist.name = new_name
        self._save_playlist(playlist)
        return playlist

    def move_playlist(self, playlist_id: str, new_parent_id: str, seq: int | None = None) -> Playlist | None:
        """Move a playlist or folder to a different parent."""
        playlist = self._get_playlist(playlist_id)
        if not playlist:
            return None
        # Prevent moving into own descendants
        if self._is_descendant(new_parent_id, playlist_id):
            raise ValueError("Cannot move playlist into its own descendant")
        playlist.parent_id = new_parent_id
        playlist.seq = seq if seq is not None else self._get_next_seq(new_parent_id)
        self._save_playlist(playlist)
        return playlist

    def delete_playlist(self, playlist_id: str, recursive: bool = False) -> bool:
        """Delete a playlist or folder. If recursive, also delete children."""
        playlist = self._get_playlist(playlist_id)
        if not playlist:
            return False

        if playlist.is_folder and not recursive:
            children = self.get_children(playlist_id)
            if children:
                raise ValueError("Folder has children. Use recursive=True to delete all.")

        if playlist.is_folder and recursive:
            for child in self.get_children(playlist_id):
                self.delete_playlist(child.id, recursive=True)

        self._delete_playlist(playlist_id)
        return True

    def _is_descendant(self, potential_ancestor: str, playlist_id: str) -> bool:
        """Check if playlist_id is a descendant of potential_ancestor."""
        current = self._get_playlist(playlist_id)
        while current and current.parent_id != "root":
            if current.parent_id == potential_ancestor:
                return True
            current = self._get_playlist(current.parent_id)
        return False

    # =========================================================================
    # Track Operations
    # =========================================================================

    def get_tracks(self, playlist_id: str) -> list[int]:
        """Get track IDs in a playlist in order."""
        self._ensure_initialized()
        if self._repository:
            return self._repository.get_tracks(playlist_id)
        playlist = self._get_playlist(playlist_id)
        return playlist.track_ids.copy() if playlist else []

    def add_tracks(
        self,
        playlist_id: str,
        track_ids: list[int],
        position: int | None = None,
        skip_duplicates: bool = True,
    ) -> Playlist | None:
        """Add tracks to a playlist."""
        playlist = self._get_playlist(playlist_id)
        if not playlist or playlist.is_folder or playlist.is_smart_playlist:
            return None

        current_tracks = self.get_tracks(playlist_id)
        existing = set(current_tracks)
        new_tracks = [tid for tid in track_ids if not skip_duplicates or tid not in existing]

        if position is None or position >= len(current_tracks):
            current_tracks.extend(new_tracks)
        else:
            current_tracks = current_tracks[:position] + new_tracks + current_tracks[position:]

        playlist.track_ids = current_tracks
        self._save_playlist(playlist)
        if self._repository:
            self._repository.set_tracks(playlist_id, playlist.track_ids)
        return playlist

    def remove_track(self, playlist_id: str, track_id: int) -> Playlist | None:
        """Remove a track from a playlist (first occurrence)."""
        playlist = self._get_playlist(playlist_id)
        if not playlist or playlist.is_folder or playlist.is_smart_playlist:
            return None

        current_tracks = self.get_tracks(playlist_id)
        try:
            current_tracks.remove(track_id)
        except ValueError:
            return None
        playlist.track_ids = current_tracks
        self._save_playlist(playlist)
        if self._repository:
            self._repository.set_tracks(playlist_id, playlist.track_ids)
        return playlist

    def remove_track_at(self, playlist_id: str, index: int) -> Playlist | None:
        """Remove a track at a specific position."""
        playlist = self._get_playlist(playlist_id)
        if not playlist or playlist.is_folder or playlist.is_smart_playlist:
            return None

        current_tracks = self.get_tracks(playlist_id)
        if 0 <= index < len(current_tracks):
            current_tracks.pop(index)
            playlist.track_ids = current_tracks
            self._save_playlist(playlist)
            if self._repository:
                self._repository.set_tracks(playlist_id, playlist.track_ids)
            return playlist
        return None

    def move_track(
        self,
        playlist_id: str,
        from_index: int,
        to_index: int,
    ) -> Playlist | None:
        """Move a track within a playlist."""
        playlist = self._get_playlist(playlist_id)
        if not playlist or playlist.is_folder or playlist.is_smart_playlist:
            return None

        current_tracks = self.get_tracks(playlist_id)
        if not (0 <= from_index < len(current_tracks)):
            return None

        track_id = current_tracks.pop(from_index)
        to_index = max(0, min(to_index, len(current_tracks)))
        current_tracks.insert(to_index, track_id)

        playlist.track_ids = current_tracks
        self._save_playlist(playlist)
        if self._repository:
            self._repository.set_tracks(playlist_id, playlist.track_ids)
        return playlist

    def copy_track(
        self,
        playlist_id: str,
        track_id: int,
        position: int | None = None,
    ) -> Playlist | None:
        """Copy a track to a position (adds duplicate)."""
        playlist = self._get_playlist(playlist_id)
        if not playlist or playlist.is_folder or playlist.is_smart_playlist:
            return None

        current_tracks = self.get_tracks(playlist_id)
        if track_id not in current_tracks:
            return None

        if position is None or position >= len(current_tracks):
            current_tracks.append(track_id)
        else:
            current_tracks.insert(position, track_id)

        playlist.track_ids = current_tracks
        self._save_playlist(playlist)
        if self._repository:
            self._repository.set_tracks(playlist_id, playlist.track_ids)
        return playlist

    def reorder(self, playlist_id: str, track_ids: list[int]) -> Playlist | None:
        """Reorder tracks to match the given order (must contain all current tracks)."""
        playlist = self._get_playlist(playlist_id)
        if not playlist or playlist.is_folder or playlist.is_smart_playlist:
            return None

        current_tracks = self.get_tracks(playlist_id)
        if set(track_ids) != set(current_tracks):
            raise ValueError("Track list must contain exactly the same tracks")

        playlist.track_ids = track_ids
        self._save_playlist(playlist)
        if self._repository:
            self._repository.set_tracks(playlist_id, playlist.track_ids)
        return playlist

    def replace_tracks(self, playlist_id: str, track_ids: list[int]) -> Playlist | None:
        """Replace all tracks in a playlist."""
        playlist = self._get_playlist(playlist_id)
        if not playlist or playlist.is_folder or playlist.is_smart_playlist:
            return None

        playlist.track_ids = track_ids
        self._save_playlist(playlist)
        if self._repository:
            self._repository.set_tracks(playlist_id, playlist.track_ids)
        return playlist

    def dedupe(self, playlist_id: str, keep: str = "first") -> Playlist | None:
        """Remove duplicate tracks from a playlist."""
        playlist = self._get_playlist(playlist_id)
        if not playlist or playlist.is_folder or playlist.is_smart_playlist:
            return None

        seen = set()
        unique = []
        for tid in self.get_tracks(playlist_id):
            if tid not in seen:
                seen.add(tid)
                unique.append(tid)
            elif keep == "last":
                # Remove previous occurrence, keep this one
                unique = [t for t in unique if t != tid]
                unique.append(tid)

        playlist.track_ids = unique
        self._save_playlist(playlist)
        if self._repository:
            self._repository.set_tracks(playlist_id, playlist.track_ids)
        return playlist

    # =========================================================================
    # Cue Batch Processing
    # =========================================================================

    def process_cues(
        self,
        playlist_id: str,
        cue_generator: callable,
        mode: str = "replace",
    ) -> dict[int, list[Any]]:
        """
        Generate cues for all tracks in a playlist.

        Args:
            playlist_id: Playlist to process
            cue_generator: Function(track_id) -> list[CuePoint] to generate cues
            mode: "replace" | "merge" | "preserve"

        Returns:
            Dict mapping track_id to generated cues
        """
        track_ids = self.get_tracks(playlist_id)
        results = {}
        for track_id in track_ids:
            cues = cue_generator(track_id)
            results[track_id] = cues
        return results

    # =========================================================================
    # Query Helpers
    # =========================================================================

    def get_playlist(self, playlist_id: str) -> Playlist | None:
        """Get a playlist by ID."""
        return self._get_playlist(playlist_id)

    def get_children(self, parent_id: str) -> list[Playlist]:
        """Get direct children of a folder."""
        self._ensure_initialized()
        if self._repository:
            return self._repository.get_children(parent_id)
        return [p for p in self._playlists.values() if p.parent_id == parent_id]

    def get_all_playlists(self) -> list[Playlist]:
        """Get all playlists and folders."""
        self._ensure_initialized()
        return list(self._playlists.values())

    def get_root_folders(self) -> list[Playlist]:
        """Get top-level folders."""
        return self.get_children("root")

    def get_playlist_tree(self, parent_id: str = "root") -> dict[str, Any]:
        """Get hierarchical tree of playlists and folders."""
        children = self.get_children(parent_id)
        result = {}
        for child in children:
            if child.is_folder:
                result[child.id] = {
                    "playlist": child,
                    "children": self.get_playlist_tree(child.id),
                }
            else:
                result[child.id] = {"playlist": child, "children": {}}
        return result

    def find_playlist_by_name(self, name: str, parent_id: str | None = None) -> Playlist | None:
        """Find a playlist by name (optionally within a parent)."""
        self._ensure_initialized()
        for playlist in self._playlists.values():
            if playlist.name == name:
                if parent_id is None or playlist.parent_id == parent_id:
                    return playlist
        return None