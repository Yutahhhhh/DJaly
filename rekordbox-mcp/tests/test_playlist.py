"""Tests for PlaylistManager (CRUD, track operations, ordering)."""

from __future__ import annotations

import pytest

from rekordbox_mcp.config import Settings
from rekordbox_mcp.db.repository import RekordboxRepository
from rekordbox_mcp.domain.models import OperationMode, Playlist
from rekordbox_mcp.domain.playlist import PlaylistManager


class InMemoryPlaylistRepository:
    """In-memory PlaylistRepository conforming to the PlaylistRepository protocol."""

    def __init__(self):
        self._playlists: dict[str, Playlist] = {}
        self._tracks: dict[str, list[int]] = {}
        root = Playlist(id="root", name="ROOT", parent_id="", attribute=1)
        self._playlists["root"] = root

    def get_all(self) -> list[Playlist]:
        return list(self._playlists.values())

    def get_by_id(self, playlist_id: str) -> Playlist | None:
        return self._playlists.get(playlist_id)

    def get_children(self, parent_id: str) -> list[Playlist]:
        return [p for p in self._playlists.values() if p.parent_id == parent_id]

    def save(self, playlist: Playlist) -> None:
        self._playlists[playlist.id] = playlist

    def delete(self, playlist_id: str) -> None:
        self._playlists.pop(playlist_id, None)
        self._tracks.pop(playlist_id, None)

    def get_tracks(self, playlist_id: str) -> list[int]:
        return self._tracks.get(playlist_id, []).copy()

    def set_tracks(self, playlist_id: str, track_ids: list[int]) -> None:
        self._tracks[playlist_id] = track_ids.copy()


@pytest.fixture
def repository() -> InMemoryPlaylistRepository:
    return InMemoryPlaylistRepository()


@pytest.fixture
def manager(repository: InMemoryPlaylistRepository) -> PlaylistManager:
    return PlaylistManager(repository=repository)


class TestCreation:
    def test_create_playlist(self, manager: PlaylistManager):
        playlist = manager.create_playlist("My Playlist")
        assert playlist.name == "My Playlist"
        assert playlist.attribute == 0
        assert playlist.is_regular_playlist
        assert playlist.parent_id == "root"

    def test_create_folder(self, manager: PlaylistManager):
        folder = manager.create_folder("My Folder")
        assert folder.is_folder
        assert folder.attribute == 1

    def test_create_playlist_assigns_incrementing_seq(self, manager: PlaylistManager):
        p1 = manager.create_playlist("A")
        p2 = manager.create_playlist("B")
        assert p2.seq == p1.seq + 1

    def test_create_smart_playlist(self, manager: PlaylistManager):
        playlist = manager.create_smart_playlist("Smart", smart_list_xml="<xml/>")
        assert playlist.is_smart_playlist
        assert playlist.smart_list_xml == "<xml/>"


class TestModification:
    def test_rename_playlist(self, manager: PlaylistManager):
        playlist = manager.create_playlist("Old Name")
        renamed = manager.rename_playlist(playlist.id, "New Name")
        assert renamed.name == "New Name"

    def test_rename_nonexistent_returns_none(self, manager: PlaylistManager):
        assert manager.rename_playlist("missing", "X") is None

    def test_move_playlist_to_new_parent(self, manager: PlaylistManager):
        folder = manager.create_folder("Folder")
        playlist = manager.create_playlist("Playlist")

        moved = manager.move_playlist(playlist.id, folder.id)
        assert moved.parent_id == folder.id

    def test_move_playlist_into_current_ancestor_raises(self, manager: PlaylistManager):
        # A -> B -> C nested chain; moving C directly under A (its own ancestor)
        # is rejected by the descendant check.
        a = manager.create_folder("A")
        b = manager.create_folder("B", parent_id=a.id)
        c = manager.create_folder("C", parent_id=b.id)

        with pytest.raises(ValueError):
            manager.move_playlist(c.id, a.id)

    def test_delete_regular_playlist(self, manager: PlaylistManager):
        playlist = manager.create_playlist("To Delete")
        assert manager.delete_playlist(playlist.id) is True
        assert manager.get_playlist(playlist.id) is None

    def test_delete_nonexistent_returns_false(self, manager: PlaylistManager):
        assert manager.delete_playlist("missing") is False

    def test_delete_folder_with_children_requires_recursive(self, manager: PlaylistManager):
        folder = manager.create_folder("Parent")
        manager.create_playlist("Child", parent_id=folder.id)

        with pytest.raises(ValueError):
            manager.delete_playlist(folder.id)

        assert manager.delete_playlist(folder.id, recursive=True) is True
        assert manager.get_children(folder.id) == []


class TestTrackOperations:
    def test_add_tracks(self, manager: PlaylistManager):
        playlist = manager.create_playlist("Tracks")
        updated = manager.add_tracks(playlist.id, [1, 2, 3])
        assert manager.get_tracks(playlist.id) == [1, 2, 3]

    def test_add_tracks_skip_duplicates(self, manager: PlaylistManager):
        playlist = manager.create_playlist("Tracks")
        manager.add_tracks(playlist.id, [1, 2])
        manager.add_tracks(playlist.id, [2, 3], skip_duplicates=True)
        assert manager.get_tracks(playlist.id) == [1, 2, 3]

    def test_add_tracks_allow_duplicates(self, manager: PlaylistManager):
        playlist = manager.create_playlist("Tracks")
        manager.add_tracks(playlist.id, [1, 2])
        manager.add_tracks(playlist.id, [2], skip_duplicates=False)
        assert manager.get_tracks(playlist.id) == [1, 2, 2]

    def test_add_tracks_at_position(self, manager: PlaylistManager):
        playlist = manager.create_playlist("Tracks")
        manager.add_tracks(playlist.id, [1, 2, 3])
        manager.add_tracks(playlist.id, [99], position=1)
        assert manager.get_tracks(playlist.id) == [1, 99, 2, 3]

    def test_add_tracks_to_folder_returns_none(self, manager: PlaylistManager):
        folder = manager.create_folder("Folder")
        assert manager.add_tracks(folder.id, [1]) is None

    def test_remove_track(self, manager: PlaylistManager):
        playlist = manager.create_playlist("Tracks")
        manager.add_tracks(playlist.id, [1, 2, 3])
        manager.remove_track(playlist.id, 2)
        assert manager.get_tracks(playlist.id) == [1, 3]

    def test_remove_track_not_in_playlist_returns_none(self, manager: PlaylistManager):
        playlist = manager.create_playlist("Tracks")
        manager.add_tracks(playlist.id, [1])
        assert manager.remove_track(playlist.id, 999) is None

    def test_remove_track_at_index(self, manager: PlaylistManager):
        playlist = manager.create_playlist("Tracks")
        manager.add_tracks(playlist.id, [1, 2, 3])
        manager.remove_track_at(playlist.id, 1)
        assert manager.get_tracks(playlist.id) == [1, 3]


class TestMoveCopyReorder:
    def test_move_track_within_playlist(self, manager: PlaylistManager):
        playlist = manager.create_playlist("Tracks")
        manager.add_tracks(playlist.id, [1, 2, 3])
        manager.move_track(playlist.id, from_index=0, to_index=2)
        assert manager.get_tracks(playlist.id) == [2, 3, 1]

    def test_move_track_invalid_index_returns_none(self, manager: PlaylistManager):
        playlist = manager.create_playlist("Tracks")
        manager.add_tracks(playlist.id, [1, 2])
        assert manager.move_track(playlist.id, from_index=5, to_index=0) is None

    def test_copy_track(self, manager: PlaylistManager):
        playlist = manager.create_playlist("Tracks")
        manager.add_tracks(playlist.id, [1, 2])
        manager.copy_track(playlist.id, track_id=1, position=1)
        assert manager.get_tracks(playlist.id) == [1, 1, 2]

    def test_copy_track_not_present_returns_none(self, manager: PlaylistManager):
        playlist = manager.create_playlist("Tracks")
        manager.add_tracks(playlist.id, [1])
        assert manager.copy_track(playlist.id, track_id=999) is None

    def test_reorder(self, manager: PlaylistManager):
        playlist = manager.create_playlist("Tracks")
        manager.add_tracks(playlist.id, [1, 2, 3])
        manager.reorder(playlist.id, [3, 1, 2])
        assert manager.get_tracks(playlist.id) == [3, 1, 2]

    def test_reorder_with_mismatched_tracks_raises(self, manager: PlaylistManager):
        playlist = manager.create_playlist("Tracks")
        manager.add_tracks(playlist.id, [1, 2, 3])
        with pytest.raises(ValueError):
            manager.reorder(playlist.id, [1, 2])

    def test_replace_tracks(self, manager: PlaylistManager):
        playlist = manager.create_playlist("Tracks")
        manager.add_tracks(playlist.id, [1, 2, 3])
        manager.replace_tracks(playlist.id, [9, 9, 9])
        assert manager.get_tracks(playlist.id) == [9, 9, 9]

    def test_dedupe_keep_first(self, manager: PlaylistManager):
        playlist = manager.create_playlist("Tracks")
        manager.add_tracks(playlist.id, [1, 2, 1, 3], skip_duplicates=False)
        manager.dedupe(playlist.id, keep="first")
        assert manager.get_tracks(playlist.id) == [1, 2, 3]

    def test_dedupe_keep_last(self, manager: PlaylistManager):
        playlist = manager.create_playlist("Tracks")
        manager.add_tracks(playlist.id, [1, 2, 1, 3], skip_duplicates=False)
        manager.dedupe(playlist.id, keep="last")
        assert manager.get_tracks(playlist.id) == [2, 1, 3]


class TestStaleCacheRegression:
    """Regression tests for the case where tracks already exist in the repository
    (e.g. added directly in Rekordbox) before ``PlaylistManager`` ever loads the
    playlist. ``get_all()``/``get_by_id()`` return a ``Playlist`` with empty
    ``track_ids`` (as the real DB-backed repository's ``_row_to_playlist`` does),
    while ``get_tracks()`` returns the real, populated list. Track mutations must
    use the latter as the source of truth and never silently wipe it out."""

    def _repo_with_preexisting_tracks(self, track_ids: list[int]) -> InMemoryPlaylistRepository:
        repo = InMemoryPlaylistRepository()
        playlist = Playlist(id="pl1", name="dance", parent_id="root", seq=0, attribute=0)
        repo._playlists["pl1"] = playlist
        repo._tracks["pl1"] = list(track_ids)
        return repo

    def test_add_tracks_with_position_preserves_existing(self):
        existing = [171130058, 146738848, 62420465, 61027647, 253890131]
        repo = self._repo_with_preexisting_tracks(existing)
        manager = PlaylistManager(repository=repo)

        manager.add_tracks("pl1", [210744670], position=2)

        assert manager.get_tracks("pl1") == [
            171130058, 146738848, 210744670, 62420465, 61027647, 253890131,
        ]

    def test_add_tracks_without_position_preserves_existing(self):
        existing = [171130058, 146738848, 62420465, 61027647, 253890131]
        repo = self._repo_with_preexisting_tracks(existing)
        manager = PlaylistManager(repository=repo)

        manager.add_tracks("pl1", [210744670])

        assert manager.get_tracks("pl1") == existing + [210744670]

    def test_remove_track_preserves_other_existing_tracks(self):
        existing = [1, 2, 3, 4, 5]
        repo = self._repo_with_preexisting_tracks(existing)
        manager = PlaylistManager(repository=repo)

        manager.remove_track("pl1", 3)

        assert manager.get_tracks("pl1") == [1, 2, 4, 5]

    def test_move_track_preserves_existing_tracks(self):
        existing = [1, 2, 3, 4, 5]
        repo = self._repo_with_preexisting_tracks(existing)
        manager = PlaylistManager(repository=repo)

        manager.move_track("pl1", from_index=0, to_index=4)

        assert manager.get_tracks("pl1") == [2, 3, 4, 5, 1]

    def test_copy_track_preserves_existing_tracks(self):
        existing = [1, 2, 3, 4, 5]
        repo = self._repo_with_preexisting_tracks(existing)
        manager = PlaylistManager(repository=repo)

        manager.copy_track("pl1", track_id=3, position=1)

        assert manager.get_tracks("pl1") == [1, 3, 2, 3, 4, 5]

    def test_dedupe_preserves_existing_tracks(self):
        existing = [1, 2, 2, 3, 4, 5]
        repo = self._repo_with_preexisting_tracks(existing)
        manager = PlaylistManager(repository=repo)

        manager.dedupe("pl1")

        assert manager.get_tracks("pl1") == [1, 2, 3, 4, 5]


class TestQueryHelpers:
    def test_get_root_folders(self, manager: PlaylistManager):
        manager.create_playlist("A")
        manager.create_folder("B")
        roots = manager.get_root_folders()
        assert {p.name for p in roots} == {"A", "B"}

    def test_get_all_playlists(self, manager: PlaylistManager):
        manager.create_playlist("A")
        manager.create_playlist("B")
        names = {p.name for p in manager.get_all_playlists()}
        assert {"A", "B"} <= names

    def test_find_playlist_by_name(self, manager: PlaylistManager):
        manager.create_playlist("Findme")
        found = manager.find_playlist_by_name("Findme")
        assert found is not None
        assert found.name == "Findme"

    def test_find_playlist_by_name_not_found(self, manager: PlaylistManager):
        assert manager.find_playlist_by_name("Nope") is None

    def test_get_playlist_tree(self, manager: PlaylistManager):
        folder = manager.create_folder("Folder")
        manager.create_playlist("Child", parent_id=folder.id)
        tree = manager.get_playlist_tree()
        assert folder.id in tree
        assert len(tree[folder.id]["children"]) == 1


class TestWithoutRepository:
    def test_manager_works_purely_in_memory(self):
        manager = PlaylistManager(repository=None)
        playlist = manager.create_playlist("Standalone")
        manager.add_tracks(playlist.id, [1, 2])
        assert manager.get_tracks(playlist.id) == [1, 2]


@pytest.fixture
def mock_repo(monkeypatch, tmp_path) -> RekordboxRepository:
    """Repository configured to use mock backend (no real database)."""
    # Create a dummy SQLite file that is NOT a Rekordbox database
    dummy_db = tmp_path / "dummy_master.db"
    dummy_db.write_bytes(b"not a rekordbox db")

    # Force mock mode by making is_rekordbox_database return False
    # and PYREKORDBOX_AVAILABLE return False (in both connection and repository modules)
    import rekordbox_mcp.db.connection as conn_module
    import rekordbox_mcp.db.repository as repo_module
    monkeypatch.setattr(conn_module, "is_rekordbox_database", lambda path: False)
    monkeypatch.setattr(conn_module, "PYREKORDBOX_AVAILABLE", False)
    monkeypatch.setattr(repo_module, "PYREKORDBOX_AVAILABLE", False)
    monkeypatch.setattr(conn_module.RekordboxConnection, "get_db_path", lambda self: dummy_db)

    settings = Settings(db_path=str(dummy_db), mode="masterdb")
    repo = RekordboxRepository(settings=settings, mode=OperationMode.MASTERDB)
    repo.connect()
    yield repo
    repo.close()


class TestRepositoryPlaylistPersistence:
    """Tests for RekordboxRepository save_playlist and delete_playlist methods."""

    def test_save_playlist_creates_new(self, mock_repo: RekordboxRepository):
        playlist = Playlist(
            id="test-new-playlist",
            name="New Playlist",
            parent_id="root",
            seq=0,
            attribute=0,
        )
        saved = mock_repo.save_playlist(playlist)

        assert saved.id == "test-new-playlist"
        assert saved.name == "New Playlist"

        # Verify it can be retrieved
        playlists = mock_repo.get_playlists()
        found = next((p for p in playlists if p.id == "test-new-playlist"), None)
        assert found is not None
        assert found.name == "New Playlist"

    def test_save_playlist_updates_existing(self, mock_repo: RekordboxRepository):
        # Create initial playlist
        playlist = Playlist(
            id="test-update-playlist",
            name="Original Name",
            parent_id="root",
            seq=0,
            attribute=0,
        )
        mock_repo.save_playlist(playlist)

        # Update it
        playlist.name = "Updated Name"
        playlist.seq = 5
        saved = mock_repo.save_playlist(playlist)

        assert saved.name == "Updated Name"
        assert saved.seq == 5

        # Verify update persisted
        playlists = mock_repo.get_playlists()
        found = next((p for p in playlists if p.id == "test-update-playlist"), None)
        assert found is not None
        assert found.name == "Updated Name"
        assert found.seq == 5

    def test_save_playlist_preserves_smart_list_xml(self, mock_repo: RekordboxRepository):
        playlist = Playlist(
            id="test-smart-playlist",
            name="Smart Playlist",
            parent_id="root",
            seq=0,
            attribute=2,  # smart playlist
            smart_list_xml='<smartlist><rule field="Genre" op="equals" value="House"/></smartlist>',
        )
        saved = mock_repo.save_playlist(playlist)

        assert saved.smart_list_xml is not None
        assert "Genre" in saved.smart_list_xml

        playlists = mock_repo.get_playlists()
        found = next((p for p in playlists if p.id == "test-smart-playlist"), None)
        assert found is not None
        assert found.smart_list_xml == playlist.smart_list_xml

    def test_delete_playlist_removes_playlist(self, mock_repo: RekordboxRepository):
        # Create playlist with tracks
        playlist = Playlist(
            id="test-delete-playlist",
            name="To Delete",
            parent_id="root",
            seq=0,
            attribute=0,
        )
        mock_repo.save_playlist(playlist)
        mock_repo.set_playlist_tracks("test-delete-playlist", [1, 2, 3])

        # Verify it exists
        assert mock_repo.get_playlist_tracks("test-delete-playlist") == [1, 2, 3]

        # Delete it
        result = mock_repo.delete_playlist("test-delete-playlist")
        assert result is True

        # Verify it's gone
        playlists = mock_repo.get_playlists()
        found = next((p for p in playlists if p.id == "test-delete-playlist"), None)
        assert found is None

        # Verify tracks are also gone
        assert mock_repo.get_playlist_tracks("test-delete-playlist") == []

    def test_delete_playlist_nonexistent_returns_false(self, mock_repo: RekordboxRepository):
        result = mock_repo.delete_playlist("nonexistent-playlist")
        assert result is False

    def test_save_playlist_rejected_in_readonly_mode(self, monkeypatch, tmp_path):
        from rekordbox_mcp.db.repository import RekordboxRepository
        from rekordbox_mcp.domain.models import OperationMode, Playlist

        dummy_db = tmp_path / "dummy_master.db"
        dummy_db.write_bytes(b"not a rekordbox db")
        import rekordbox_mcp.db.connection as conn_module
        import rekordbox_mcp.db.repository as repo_module
        monkeypatch.setattr(conn_module, "is_rekordbox_database", lambda path: False)
        monkeypatch.setattr(conn_module, "PYREKORDBOX_AVAILABLE", False)
        monkeypatch.setattr(repo_module, "PYREKORDBOX_AVAILABLE", False)
        monkeypatch.setattr(conn_module.RekordboxConnection, "get_db_path", lambda self: dummy_db)

        settings = Settings(db_path=str(dummy_db), mode="readonly")
        repo = RekordboxRepository(settings=settings, mode=OperationMode.READONLY)
        repo.connect()

        playlist = Playlist(
            id="test-readonly",
            name="Readonly Test",
            parent_id="root",
            seq=0,
            attribute=0,
        )

        with pytest.raises(RuntimeError, match="Playlist save only allowed in masterdb mode"):
            repo.save_playlist(playlist)

        repo.close()

    def test_delete_playlist_rejected_in_readonly_mode(self, monkeypatch, tmp_path):
        from rekordbox_mcp.db.repository import RekordboxRepository
        from rekordbox_mcp.domain.models import OperationMode

        dummy_db = tmp_path / "dummy_master.db"
        dummy_db.write_bytes(b"not a rekordbox db")
        import rekordbox_mcp.db.connection as conn_module
        import rekordbox_mcp.db.repository as repo_module
        monkeypatch.setattr(conn_module, "is_rekordbox_database", lambda path: False)
        monkeypatch.setattr(conn_module, "PYREKORDBOX_AVAILABLE", False)
        monkeypatch.setattr(repo_module, "PYREKORDBOX_AVAILABLE", False)
        monkeypatch.setattr(conn_module.RekordboxConnection, "get_db_path", lambda self: dummy_db)

        settings = Settings(db_path=str(dummy_db), mode="readonly")
        repo = RekordboxRepository(settings=settings, mode=OperationMode.READONLY)
        repo.connect()

        with pytest.raises(RuntimeError, match="Playlist deletion only allowed in masterdb mode"):
            repo.delete_playlist("some-playlist")

        repo.close()
