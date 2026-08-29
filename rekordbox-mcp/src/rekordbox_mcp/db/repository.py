"""Rekordbox database repository for reading and writing track, cue, and playlist data."""

from __future__ import annotations

import threading
from pathlib import Path

from rekordbox_mcp.config import Settings, get_settings
from rekordbox_mcp.db.connection import (
    PYREKORDBOX_AVAILABLE,
    RekordboxConnection,
    is_rekordbox_database,
)
from rekordbox_mcp.domain.models import (
    BeatGrid,
    CuePoint,
    OperationMode,
    Playlist,
    Track,
    WaveformPoint,
)

# Try to import pyrekordbox for ANLZ parsing
try:
    import pyrekordbox
    from pyrekordbox.anlz import AnlzFile

    PYREKORDBOX_ANLZ_AVAILABLE = True
except ImportError:
    pyrekordbox = None
    AnlzFile = None
    PYREKORDBOX_ANLZ_AVAILABLE = False


class MockDatabase:
    """In-memory mock database for testing when pyrekordbox is not available."""

    def __init__(self):
        self._tracks: dict[int, dict] = {}
        self._cues: dict[str, dict] = {}
        self._playlists: dict[str, dict] = {}
        self._playlist_content: dict[str, list[int]] = {}
        self._lock = threading.RLock()
        self._next_cue_id = 1
        self._next_playlist_id = 1

        # Add some mock data
        self._init_mock_data()

    def _init_mock_data(self):
        """Initialize with some mock tracks."""
        mock_tracks = [
            {
                "ID": 1,
                "Title": "Mock Track 1",
                "Artist": "Mock Artist 1",
                "AverageBpm": 12800,  # BPM * 100
                "TotalTime": 300000,  # ms
                "AnalysisPath": "/mock/analysis/1.anlz",
                "Key": "5A",
                "Genre": "House",
            },
            {
                "ID": 2,
                "Title": "Mock Track 2",
                "Artist": "Mock Artist 2",
                "AverageBpm": 12400,
                "TotalTime": 280000,
                "AnalysisPath": "/mock/analysis/2.anlz",
                "Key": "8B",
                "Genre": "Techno",
            },
        ]
        for t in mock_tracks:
            self._tracks[t["ID"]] = t

        # Mock playlists
        self._playlists["root"] = {
            "ID": "root",
            "Name": "ROOT",
            "ParentID": "",
            "Seq": 0,
            "Attribute": 1,
            "SmartListXML": None,
        }
        self._playlists["pl1"] = {
            "ID": "pl1",
            "Name": "My Playlist",
            "ParentID": "root",
            "Seq": 0,
            "Attribute": 0,
            "SmartListXML": None,
        }
        self._playlist_content["pl1"] = [1, 2]

    def get_content_table(self):
        return MockTable(self._tracks)

    def get_cue_table(self):
        return MockTable(self._cues)

    def get_playlist_table(self):
        return MockTable(self._playlists)

    def get_playlist_content_table(self):
        return MockPlaylistContentTable(self._playlist_content)


class MockTable:
    """Mock table for in-memory operations."""

    def __init__(self, data: dict):
        self._data = data
        self._lock = threading.RLock()

    def get_all(self):
        with self._lock:
            return list(self._data.values())

    def get_by_id(self, id_val):
        with self._lock:
            return self._data.get(id_val)

    def insert(self, record):
        with self._lock:
            if "ID" not in record:
                record["ID"] = str(len(self._data) + 1)
            self._data[record["ID"]] = record
            return record

    def update(self, id_val, updates):
        with self._lock:
            if id_val in self._data:
                self._data[id_val].update(updates)
                return self._data[id_val]
            return None

    def delete(self, id_val):
        with self._lock:
            if id_val in self._data:
                del self._data[id_val]
                return True
            return False


class MockPlaylistContentTable:
    """Mock playlist content table."""

    def __init__(self, data: dict[str, list[int]]):
        self._data = data
        self._lock = threading.RLock()

    def get_tracks(self, playlist_id: str) -> list[int]:
        with self._lock:
            return self._data.get(playlist_id, []).copy()

    def set_tracks(self, playlist_id: str, track_ids: list[int]):
        with self._lock:
            self._data[playlist_id] = track_ids.copy()

    def add_track(self, playlist_id: str, track_id: int, position: int | None = None):
        with self._lock:
            if playlist_id not in self._data:
                self._data[playlist_id] = []
            tracks = self._data[playlist_id]
            if position is None or position >= len(tracks):
                tracks.append(track_id)
            else:
                tracks.insert(position, track_id)

    def remove_track(self, playlist_id: str, track_id: int) -> bool:
        with self._lock:
            if playlist_id in self._data:
                try:
                    self._data[playlist_id].remove(track_id)
                    return True
                except ValueError:
                    return False
            return False


class RekordboxRepository:
    """Repository for accessing Rekordbox database with three operation modes."""

    def __init__(
        self,
        settings: Settings | None = None,
        mode: OperationMode | str = OperationMode.READONLY,
    ):
        self._settings = settings or get_settings()
        self._mode = OperationMode(mode) if isinstance(mode, str) else mode
        self._connection = RekordboxConnection(self._settings, self._mode)
        self._mock_db: MockDatabase | None = None
        db_path = self._connection.get_db_path()
        # A missing database is *not* a mock-backend case: the mock fallback is
        # only for placeholder SQLite files (tests / no pyrekordbox).  When no
        # master.db exists at all the repository must report the database as
        # unavailable instead of silently serving mock data.
        self._db_unavailable = db_path is None
        self._use_mock = not self._db_unavailable and (
            not PYREKORDBOX_AVAILABLE or not is_rekordbox_database(db_path)
        )

    def _ensure_db_available(self) -> None:
        """Raise a clear error when the Rekordbox database is unavailable."""
        if self._db_unavailable:
            raise RuntimeError(
                "Rekordbox database not found or not available. "
                "The server is running without a Rekordbox database; "
                "database-dependent operations are unavailable.",
            )

    def connect(self) -> None:
        """Connect to the database."""
        if self._use_mock:
            self._mock_db = MockDatabase()
        else:
            self._ensure_db_available()
            self._connection.connect()

    def close(self) -> None:
        """Close the database connection."""
        if not self._use_mock:
            self._connection.close()

    def __enter__(self) -> RekordboxRepository:
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()

    @property
    def mode(self) -> OperationMode:
        return self._mode

    @property
    def is_mock(self) -> bool:
        return self._use_mock

    # =========================================================================
    # Track Operations
    # =========================================================================

    def get_tracks(self, filter: dict | None = None) -> list[Track]:
        """Get all tracks with optional filtering. BPM is stored as *100 in DB."""
        if self._use_mock:
            return self._get_tracks_mock(filter)

        self._ensure_db_available()
        self._connection.connect()
        content_table = self._connection.get_content_table()
        if not content_table:
            return []

        try:
            rows = content_table.get_all()
        except Exception as e:
            self._connection.recover_from_error(e)
            raise RuntimeError(f"Failed to read tracks: {e}") from e
        tracks = []
        for row in rows:
            # Listing the library must not parse every cue and ANLZ file.
            # Those expensive details are loaded by get_track() instead.
            track = self._row_to_track(row, load_details=False)
            if track and self._matches_filter(track, filter):
                tracks.append(track)
        return tracks

    def _get_tracks_mock(self, filter: dict | None = None) -> list[Track]:
        tracks = []
        for row in self._mock_db.get_content_table().get_all():
            track = self._row_to_track(row)
            if track and self._matches_filter(track, filter):
                tracks.append(track)
        return tracks

    def get_track(self, track_id: int) -> Track | None:
        """Get a single track by ID."""
        if self._use_mock:
            row = self._mock_db.get_content_table().get_by_id(track_id)
            if row:
                return self._row_to_track(row)
            return None

        self._ensure_db_available()
        self._connection.connect()
        content_table = self._connection.get_content_table()
        if not content_table:
            return None

        row = content_table.get_by_id(track_id)
        if row:
            return self._row_to_track(row)
        return None

    def _row_to_track(self, row: dict, load_details: bool = True) -> Track | None:
        """Convert database row to Track model."""
        try:
            track_id = row.get("ID")
            if track_id is None:
                return None

            # BPM is stored as *100 in rekordbox
            bpm_raw = row.get("AverageBpm", 0)
            bpm = bpm_raw / 100.0 if bpm_raw else 0.0

            # Duration in milliseconds
            duration_ms = float(row.get("TotalTime", 0))

            # Create beat grid from first beat and BPM
            first_beat_ms = float(row.get("FirstBeat", 0))
            beat_grid = None
            if bpm > 0:
                beat_grid = BeatGrid(first_beat_ms=first_beat_ms, bpm=bpm)

            track = Track(
                id=int(track_id),
                title=row.get("Title", ""),
                artist=row.get("Artist", ""),
                bpm=bpm,
                duration_ms=duration_ms,
                analysis_path=row.get("AnalysisPath", ""),
                key=row.get("Key") or None,
                genre=row.get("Genre") or None,
                beat_grid=beat_grid,
            )

            if load_details:
                # Load cues and ANLZ analysis only for a single-track request.
                track.cues = self.get_cues(track.id)
                anlz_data = self.read_anlz_files(track)
                if anlz_data:
                    track.phrases = anlz_data.get("phrases", [])
                    track.waveform = anlz_data.get("waveform")
                    track.vocal_track = anlz_data.get("vocal_track")

            return track
        except Exception:
            return None

    def _matches_filter(self, track: Track, filter: dict | None) -> bool:
        if not filter:
            return True
        # ``query`` matches title OR artist (partial, case-insensitive).
        if "query" in filter:
            q = filter["query"].lower()
            if q not in track.title.lower() and q not in track.artist.lower():
                return False
        if "genre" in filter and track.genre != filter["genre"]:
            return False
        if "artist" in filter and filter["artist"].lower() not in track.artist.lower():
            return False
        if "title" in filter and filter["title"].lower() not in track.title.lower():
            return False
        if "min_bpm" in filter and track.bpm < filter["min_bpm"]:
            return False
        if "max_bpm" in filter and track.bpm > filter["max_bpm"]:
            return False
        return True

    # =========================================================================
    # Cue Operations
    # =========================================================================

    def get_cues(self, track_id: int) -> list[CuePoint]:
        """Get all cue points for a track. InMsec is stored as milliseconds."""
        if self._mode == OperationMode.XML:
            xml_path = self._settings.xml_path_obj
            if xml_path.exists():
                from rekordbox_mcp.db.xml_writer import RekordboxXmlWriter
                return RekordboxXmlWriter(xml_path).get_cues_for_track(track_id)
            return []
        if self._use_mock:
            return self._get_cues_mock(track_id)

        self._ensure_db_available()
        self._connection.connect()
        cue_table = self._connection.get_cue_table()
        if not cue_table:
            return []

        # Query cues for this track
        rows = cue_table.get_all()
        cues = []
        for row in rows:
            if row.get("ContentID") == track_id:
                cue = CuePoint.from_db_dict(row)
                cues.append(cue)
        return cues

    def get_cue(self, cue_id: str) -> CuePoint | None:
        """Get a cue point by ID, including the track it belongs to."""
        if self._mode == OperationMode.XML:
            for track in self.get_tracks():
                for cue in track.cues:
                    if cue.id == cue_id:
                        return cue
            return None
        if self._use_mock:
            row = self._mock_db.get_cue_table().get_by_id(cue_id)
            return CuePoint.from_db_dict(row) if row else None

        self._ensure_db_available()
        self._connection.connect()
        cue_table = self._connection.get_cue_table()
        if not cue_table:
            return None

        row = cue_table.get_by_id(cue_id)
        return CuePoint.from_db_dict(row) if row else None

    def _get_cues_mock(self, track_id: int) -> list[CuePoint]:
        cues = []
        for row in self._mock_db.get_cue_table().get_all():
            if row.get("ContentID") == track_id:
                cues.append(CuePoint.from_db_dict(row))
        return cues

    def add_cue(self, track_id: int, cue: CuePoint) -> CuePoint:
        """Add a cue point to a track. Only allowed in masterdb mode."""
        if self._mode != OperationMode.MASTERDB:
            raise RuntimeError("Cue creation only allowed in masterdb mode")

        if self._use_mock:
            return self._add_cue_mock(track_id, cue)

        self._ensure_db_available()
        self._connection.connect()

        # Verify Rekordbox is not running
        if self._connection.is_rekordbox_running():
            raise RuntimeError("Rekordbox is running. Cannot write to database.")

        cue_table = self._connection.get_cue_table()
        if not cue_table:
            raise RuntimeError("Cue table not available")

        # Prepare cue data for database
        cue_data = cue.to_db_dict()
        cue_data["ContentID"] = track_id

        # Insert using pyrekordbox
        try:
            # Use the pyrekordbox table insert method
            new_record = cue_table.insert(cue_data)
            if new_record:
                return CuePoint.from_db_dict(new_record)
        except Exception as e:
            raise RuntimeError(f"Failed to add cue: {e}") from e

        raise RuntimeError("Failed to add cue")

    def _add_cue_mock(self, track_id: int, cue: CuePoint) -> CuePoint:
        cue_data = cue.to_db_dict()
        cue_data["ContentID"] = track_id
        cue_data["ID"] = f"mock_cue_{self._mock_db._next_cue_id}"
        self._mock_db._next_cue_id += 1
        self._mock_db.get_cue_table().insert(cue_data)
        return CuePoint.from_db_dict(cue_data)

    def update_cue(self, cue_id: str, data: dict) -> CuePoint | None:
        """Update a cue point. Only allowed in masterdb mode."""
        if self._mode != OperationMode.MASTERDB:
            raise RuntimeError("Cue update only allowed in masterdb mode")

        if self._use_mock:
            return self._update_cue_mock(cue_id, data)

        self._ensure_db_available()
        self._connection.connect()

        if self._connection.is_rekordbox_running():
            raise RuntimeError("Rekordbox is running. Cannot write to database.")

        cue_table = self._connection.get_cue_table()
        if not cue_table:
            raise RuntimeError("Cue table not available")

        # Convert data to DB format
        db_data = {}
        if "position_ms" in data:
            db_data["InMsec"] = int(data["position_ms"])
        if "loop_end_ms" in data:
            db_data["OutMsec"] = int(data["loop_end_ms"]) if data["loop_end_ms"] else 0
        if "comment" in data:
            db_data["Comment"] = data["comment"]
        if "color_table_index" in data:
            db_data["ColorTableIndex"] = data["color_table_index"]
        if "color" in data:
            db_data["Color"] = data["color"]
        if "kind" in data:
            db_data["Kind"] = data["kind"]

        db_data["UpdatedAt"] = __import__("datetime").datetime.now()

        try:
            updated = cue_table.update(cue_id, db_data)
            if updated:
                return CuePoint.from_db_dict(updated)
        except Exception as e:
            raise RuntimeError(f"Failed to update cue: {e}") from e

        return None

    def _update_cue_mock(self, cue_id: str, data: dict) -> CuePoint | None:
        db_data = {}
        if "position_ms" in data:
            db_data["InMsec"] = int(data["position_ms"])
        if "loop_end_ms" in data:
            db_data["OutMsec"] = int(data["loop_end_ms"]) if data["loop_end_ms"] else 0
        if "comment" in data:
            db_data["Comment"] = data["comment"]
        if "color_table_index" in data:
            db_data["ColorTableIndex"] = data["color_table_index"]
        if "color" in data:
            db_data["Color"] = data["color"]
        if "kind" in data:
            db_data["Kind"] = data["kind"]

        updated = self._mock_db.get_cue_table().update(cue_id, db_data)
        if updated:
            return CuePoint.from_db_dict(updated)
        return None

    def delete_cue(self, cue_id: str) -> bool:
        """Delete a cue point. Only allowed in masterdb mode."""
        if self._mode != OperationMode.MASTERDB:
            raise RuntimeError("Cue deletion only allowed in masterdb mode")

        if self._use_mock:
            return self._mock_db.get_cue_table().delete(cue_id)

        self._ensure_db_available()
        self._connection.connect()

        if self._connection.is_rekordbox_running():
            raise RuntimeError("Rekordbox is running. Cannot write to database.")

        cue_table = self._connection.get_cue_table()
        if not cue_table:
            raise RuntimeError("Cue table not available")

        try:
            return cue_table.delete(cue_id)
        except Exception as e:
            raise RuntimeError(f"Failed to delete cue: {e}") from e

    # =========================================================================
    # Playlist Operations
    # =========================================================================

    def get_playlists(self) -> list[Playlist]:
        """Get all playlists and folders."""
        if self._use_mock:
            return self._get_playlists_mock()

        self._ensure_db_available()
        self._connection.connect()
        playlist_table = self._connection.get_playlist_table()
        if not playlist_table:
            return []

        try:
            rows = playlist_table.get_all()
        except Exception as e:
            self._connection.recover_from_error(e)
            raise RuntimeError(f"Failed to read playlists: {e}") from e
        playlists = []
        for row in rows:
            playlist = self._row_to_playlist(row)
            if playlist:
                playlists.append(playlist)
        return playlists

    def _get_playlists_mock(self) -> list[Playlist]:
        playlists = []
        for row in self._mock_db.get_playlist_table().get_all():
            playlist = self._row_to_playlist(row)
            if playlist:
                playlists.append(playlist)
        return playlists

    def _row_to_playlist(self, row: dict) -> Playlist | None:
        try:
            return Playlist(
                id=str(row.get("ID", "")),
                name=row.get("Name", ""),
                parent_id=str(row.get("ParentID", "root")),
                seq=row.get("Seq", 0),
                attribute=row.get("Attribute", 0),
                smart_list_xml=row.get("SmartListXML"),
            )
        except Exception:
            return None

    def get_playlist_tracks(self, playlist_id: str) -> list[int]:
        """Get track IDs in a playlist in order."""
        if self._use_mock:
            return self._mock_db.get_playlist_content_table().get_tracks(playlist_id)

        self._ensure_db_available()
        self._connection.connect()
        content_table = self._connection.get_playlist_content_table()
        if not content_table:
            return []

        # In pyrekordbox 0.4.x playlist membership is represented by
        # ``DjmdSongPlaylist``.  The generic table adapter intentionally only
        # exposes get_all/get_by_id, so query the database model directly here
        # and preserve Rekordbox's TrackNo ordering.
        try:
            rows = self._connection.db.get_playlist_songs(
                PlaylistID=str(playlist_id),
            ).all()
            rows.sort(key=lambda row: (row.TrackNo is None, row.TrackNo or 0))
            return [int(row.ContentID) for row in rows if row.ContentID is not None]
        except Exception as e:
            self._connection.recover_from_error(e)
            raise RuntimeError(f"Failed to read playlist tracks: {e}") from e

    def set_playlist_tracks(self, playlist_id: str, track_ids: list[int]) -> None:
        """Replace all tracks in a playlist with the given ordered list. Only allowed in masterdb mode."""
        if self._mode != OperationMode.MASTERDB:
            raise RuntimeError("Playlist modification only allowed in masterdb mode")

        if self._use_mock:
            self._mock_db.get_playlist_content_table().set_tracks(playlist_id, track_ids)
            return

        self._ensure_db_available()
        self._connection.connect()

        if self._connection.is_rekordbox_running():
            raise RuntimeError("Rekordbox is running. Cannot write to database.")

        content_table = self._connection.get_playlist_content_table()
        if not content_table:
            raise RuntimeError("Playlist content table not available")

        try:
            content_table.set_tracks(playlist_id, track_ids)
        except Exception as e:
            self._connection.recover_from_error(e)
            raise RuntimeError(f"Failed to set playlist tracks: {e}") from e

    def create_playlist(self, name: str, parent_id: str = "root") -> Playlist:
        """Create a new playlist. Only allowed in masterdb mode."""
        if self._mode != OperationMode.MASTERDB:
            raise RuntimeError("Playlist creation only allowed in masterdb mode")

        if self._use_mock:
            return self._create_playlist_mock(name, parent_id)

        self._ensure_db_available()
        self._connection.connect()

        if self._connection.is_rekordbox_running():
            raise RuntimeError("Rekordbox is running. Cannot write to database.")

        playlist_table = self._connection.get_playlist_table()
        if not playlist_table:
            raise RuntimeError("Playlist table not available")

        import uuid
        playlist_id = str(uuid.uuid4())

        # Get next sequence number
        seq = self._get_next_seq(parent_id)

        playlist_data = {
            "ID": playlist_id,
            "Name": name,
            "ParentID": parent_id,
            "Seq": seq,
            "Attribute": 0,  # regular playlist
            "SmartListXML": None,
        }

        try:
            inserted = playlist_table.insert(playlist_data)
            # master.db stores playlist IDs as integers; use the ID the
            # database actually assigned instead of the UUID placeholder.
            actual_id = str(inserted.get("ID", playlist_id))
            return Playlist(
                id=actual_id,
                name=name,
                parent_id=parent_id,
                seq=seq,
                attribute=0,
            )
        except Exception as e:
            raise RuntimeError(f"Failed to create playlist: {e}") from e

    def _create_playlist_mock(self, name: str, parent_id: str) -> Playlist:
        import uuid
        playlist_id = str(uuid.uuid4())
        seq = self._get_next_seq_mock(parent_id)

        playlist_data = {
            "ID": playlist_id,
            "Name": name,
            "ParentID": parent_id,
            "Seq": seq,
            "Attribute": 0,
            "SmartListXML": None,
        }
        self._mock_db.get_playlist_table().insert(playlist_data)
        self._mock_db.get_playlist_content_table().set_tracks(playlist_id, [])

        return Playlist(
            id=playlist_id,
            name=name,
            parent_id=parent_id,
            seq=seq,
            attribute=0,
        )

    def save_playlist(self, playlist: Playlist) -> Playlist:
        """Save (upsert) a playlist. Creates if not exists, updates if exists. Only allowed in masterdb mode."""
        if self._mode != OperationMode.MASTERDB:
            raise RuntimeError("Playlist save only allowed in masterdb mode")

        if self._use_mock:
            return self._save_playlist_mock(playlist)

        self._ensure_db_available()
        self._connection.connect()

        if self._connection.is_rekordbox_running():
            raise RuntimeError("Rekordbox is running. Cannot write to database.")

        playlist_table = self._connection.get_playlist_table()
        if not playlist_table:
            raise RuntimeError("Playlist table not available")

        playlist_data = {
            "ID": playlist.id,
            "Name": playlist.name,
            "ParentID": playlist.parent_id,
            "Seq": playlist.seq,
            "Attribute": playlist.attribute,
            "SmartListXML": playlist.smart_list_xml,
        }

        try:
            # Check if playlist exists
            existing = playlist_table.get_by_id(playlist.id)
            if existing:
                # Update existing playlist
                playlist_table.update(playlist.id, playlist_data)
            else:
                # Insert new playlist (respects the ID provided by PlaylistManager)
                inserted = playlist_table.insert(playlist_data)
                # master.db stores playlist IDs as integers; reflect the ID the
                # database actually assigned so callers keep using a valid ID.
                actual_id = str(inserted.get("ID", playlist.id))
                if actual_id != playlist.id:
                    playlist.id = actual_id
        except Exception as e:
            self._connection.recover_from_error(e)
            raise RuntimeError(f"Failed to save playlist: {e}") from e
        return playlist

    def _save_playlist_mock(self, playlist: Playlist) -> Playlist:
        playlist_data = {
            "ID": playlist.id,
            "Name": playlist.name,
            "ParentID": playlist.parent_id,
            "Seq": playlist.seq,
            "Attribute": playlist.attribute,
            "SmartListXML": playlist.smart_list_xml,
        }
        self._mock_db.get_playlist_table().insert(playlist_data)
        # Ensure playlist content entry exists
        if playlist.id not in self._mock_db._playlist_content:
            self._mock_db._playlist_content[playlist.id] = []
        return playlist

    def delete_playlist(self, playlist_id: str) -> bool:
        """Delete a playlist. Only allowed in masterdb mode."""
        if self._mode != OperationMode.MASTERDB:
            raise RuntimeError("Playlist deletion only allowed in masterdb mode")

        if self._use_mock:
            return self._delete_playlist_mock(playlist_id)

        self._ensure_db_available()
        self._connection.connect()

        if self._connection.is_rekordbox_running():
            raise RuntimeError("Rekordbox is running. Cannot write to database.")

        playlist_table = self._connection.get_playlist_table()
        if not playlist_table:
            raise RuntimeError("Playlist table not available")

        try:
            # Also delete playlist content (tracks)
            content_table = self._connection.get_playlist_content_table()
            if content_table:
                # Remove all tracks from playlist first
                existing_tracks = content_table.get_tracks(playlist_id)
                for track_id in existing_tracks:
                    content_table.remove_track(playlist_id, track_id)

            # Delete the playlist itself
            return playlist_table.delete(playlist_id)
        except Exception as e:
            raise RuntimeError(f"Failed to delete playlist: {e}") from e

    def _delete_playlist_mock(self, playlist_id: str) -> bool:
        # Delete playlist content
        self._mock_db.get_playlist_content_table().set_tracks(playlist_id, [])
        # Delete playlist
        return self._mock_db.get_playlist_table().delete(playlist_id)

    def _get_next_seq(self, parent_id: str) -> int:
        playlists = self.get_playlists()
        children = [p for p in playlists if p.parent_id == parent_id]
        return max((p.seq for p in children), default=-1) + 1

    def _get_next_seq_mock(self, parent_id: str) -> int:
        playlists = self._get_playlists_mock()
        children = [p for p in playlists if p.parent_id == parent_id]
        return max((p.seq for p in children), default=-1) + 1

    def add_tracks_to_playlist(self, playlist_id: str, track_ids: list[int]) -> None:
        """Add tracks to a playlist. Only allowed in masterdb mode."""
        if self._mode != OperationMode.MASTERDB:
            raise RuntimeError("Playlist modification only allowed in masterdb mode")

        if self._use_mock:
            self._add_tracks_to_playlist_mock(playlist_id, track_ids)
            return

        self._ensure_db_available()
        self._connection.connect()

        if self._connection.is_rekordbox_running():
            raise RuntimeError("Rekordbox is running. Cannot write to database.")

        content_table = self._connection.get_playlist_content_table()
        if not content_table:
            raise RuntimeError("Playlist content table not available")

        for track_id in track_ids:
            try:
                content_table.add_track(playlist_id, track_id)
            except Exception as e:
                raise RuntimeError(f"Failed to add track {track_id} to playlist: {e}") from e

    def _add_tracks_to_playlist_mock(self, playlist_id: str, track_ids: list[int]) -> None:
        for track_id in track_ids:
            self._mock_db.get_playlist_content_table().add_track(playlist_id, track_id)

    def remove_track_from_playlist(self, playlist_id: str, track_id: int) -> bool:
        """Remove a track from a playlist. Only allowed in masterdb mode."""
        if self._mode != OperationMode.MASTERDB:
            raise RuntimeError("Playlist modification only allowed in masterdb mode")

        if self._use_mock:
            return self._mock_db.get_playlist_content_table().remove_track(playlist_id, track_id)

        self._ensure_db_available()
        self._connection.connect()

        if self._connection.is_rekordbox_running():
            raise RuntimeError("Rekordbox is running. Cannot write to database.")

        content_table = self._connection.get_playlist_content_table()
        if not content_table:
            raise RuntimeError("Playlist content table not available")

        try:
            return content_table.remove_track(playlist_id, track_id)
        except Exception as e:
            raise RuntimeError(f"Failed to remove track from playlist: {e}") from e

    # =========================================================================
    # ANLZ File Analysis
    # =========================================================================

    def read_anlz_files(self, track: Track) -> dict:
        """
        Parse ANLZ analysis file for a track.
        Returns dict with phrases, beat_grid, waveform, vocal_track.
        """
        result = {
            "phrases": [],
            "beat_grid": None,
            "waveform": None,
            "vocal_track": None,
        }

        if not track.analysis_path:
            return result

        anlz_path = Path(track.analysis_path)
        if not anlz_path.exists():
            # Try to find in db_dir
            if self._settings.db_dir_obj:
                alt_path = self._settings.db_dir_obj / "Analysis" / anlz_path.name
                if alt_path.exists():
                    anlz_path = alt_path

        if not anlz_path.exists():
            return result

        if self._use_mock or not PYREKORDBOX_ANLZ_AVAILABLE:
            return self._read_anlz_mock(track)

        try:
            anlz = AnlzFile(str(anlz_path))
            anlz_data = anlz.parse()

            # Parse phrases (PSSI)
            if "pssi" in anlz_data or "song_structure" in anlz_data:
                from rekordbox_mcp.domain.phrase import analyze_phrases_from_anlz
                if track.beat_grid:
                    phrase_result = analyze_phrases_from_anlz(
                        anlz_data, track.beat_grid, track.duration_ms,
                    )
                    result["phrases"] = phrase_result.phrases

            # Parse beat grid (PQTZ)
            if "pqtz" in anlz_data:
                pqtz = anlz_data["pqtz"]
                if track.beat_grid:
                    # Update beat grid with more precise data if available
                    pass

            # Parse waveform (PWV5)
            if "pwv5" in anlz_data:
                pwv5 = anlz_data["pwv5"]
                result["waveform"] = self._parse_waveform(pwv5)

            # Parse vocal (PVDI)
            if "pvdi" in anlz_data:
                pvdi = anlz_data["pvdi"]
                result["vocal_track"] = self._parse_vocal(pvdi)

        except Exception:
            # Silently fail - ANLZ parsing is best effort
            pass

        return result

    def _read_anlz_mock(self, track: Track) -> dict:
        """Mock ANLZ data for testing."""
        from rekordbox_mcp.domain.phrase import create_default_phrases

        result = {
            "phrases": [],
            "beat_grid": None,
            "waveform": None,
            "vocal_track": None,
        }

        if track.beat_grid:
            result["phrases"] = create_default_phrases(track.beat_grid, track.duration_ms)
            result["beat_grid"] = track.beat_grid

        # Mock waveform
        result["waveform"] = [
            WaveformPoint(height=0.5, red=3, green=4, blue=2)
            for _ in range(100)
        ]

        # Mock vocal track
        result["vocal_track"] = [0, 0, 1, 2, 3, 4, 3, 2, 1, 0] * 10

        return result

    def _parse_waveform(self, pwv5_data: dict) -> list[WaveformPoint]:
        """Parse PWV5 waveform data."""
        points = []
        if "points" in pwv5_data:
            for p in pwv5_data["points"]:
                points.append(WaveformPoint(
                    height=p.get("height", 0.0),
                    red=p.get("red", 0),
                    green=p.get("green", 0),
                    blue=p.get("blue", 0),
                ))
        return points

    def _parse_vocal(self, pvdi_data: dict) -> list[int]:
        """Parse PVDI vocal track data."""
        if "vocal_track" in pvdi_data:
            return pvdi_data["vocal_track"]
        return []


# Export
__all__ = ["RekordboxRepository"]
