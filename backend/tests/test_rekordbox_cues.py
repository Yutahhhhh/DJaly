from pathlib import Path

import pytest


@pytest.fixture
def client(session):
    # Exercise the real HTTP contract and DB without unrelated app integrations.
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from api.routers.performance_metadata import router
    from infra.database.connection import get_session
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_session] = lambda: session
    with TestClient(app) as value:
        yield value


@pytest.fixture(autouse=True)
def query_only_audio_clock(monkeypatch):
    # These SQL/API fixtures use imaginary audio paths on every OS. Real header
    # classification and compensation live in workflow_integrity tests.
    monkeypatch.setattr("infra.rekordbox_cues.timing_offset_ms", lambda _: 0.)
from sqlmodel import Session

from api.schemas.performance_metadata import CuePoint, PerformanceMetadataWrite
from app.services.performance_metadata_app_service import PerformanceMetadataAppService
from domain.models.track import Track
from infra import rekordbox_cues
from infra.database import connection as db_connection
from tests.test_performance_metadata import _track


class FakeConnection:
    def __init__(self, cue_rows=()):
        self.cue_rows = list(cue_rows)
        self.calls = []
        self.closed = False

    def execute(self, statement, params):
        self.calls.append((statement, params))
        if "FROM djmdContent" in statement:
            return FakeRows([("rb-track",)])
        return FakeRows(self.cue_rows)

    def close(self):
        self.closed = True


class FakeRows:
    def __init__(self, rows):
        self.rows = rows

    def fetchall(self):
        return self.rows


def test_reader_maps_rekordbox_kinds_to_eight_plumdeck_slots(tmp_path, monkeypatch):
    database = tmp_path / "master.db"
    database.touch()
    connection = FakeConnection([
        (1, 125, "Intro"),
        (5, 4125, "Drop"),
        (9, 8125, None),
    ])
    monkeypatch.setattr(rekordbox_cues, "connect_readonly", lambda _: connection)

    cues = rekordbox_cues.read_hot_cues("/music/exact.mp3", database)

    assert [cue.model_dump() for cue in cues] == [
        {"slot": 0, "position_ms": 125, "label": "Intro", "color": None},
        {"slot": 3, "position_ms": 4125, "label": "Drop", "color": None},
        {"slot": 7, "position_ms": 8125, "label": "H", "color": None},
    ]
    assert connection.calls[0][1] == ("/music/exact.mp3",)
    assert "/music/exact.mp3" not in connection.calls[0][0]
    assert connection.calls[1][1] == ("rb-track", 1, 2, 3, 5, 6, 7, 8, 9)
    assert connection.closed is True


def test_reader_distinguishes_missing_track_from_track_with_no_cues(tmp_path, monkeypatch):
    database = tmp_path / "master.db"
    database.touch()
    empty = FakeConnection()
    monkeypatch.setattr(rekordbox_cues, "connect_readonly", lambda _: empty)
    assert rekordbox_cues.read_hot_cues("/music/exact.mp3", database) == []

    class MissingConnection(FakeConnection):
        def execute(self, statement, params):
            self.calls.append((statement, params))
            return FakeRows([])

    monkeypatch.setattr(rekordbox_cues, "connect_readonly", lambda _: MissingConnection())
    with pytest.raises(rekordbox_cues.RekordboxCueTrackNotFoundError):
        rekordbox_cues.read_hot_cues("/music/missing.mp3", database)


def test_bulk_reader_uses_one_connection_and_bounded_path_queries(tmp_path, monkeypatch):
    database = tmp_path / "master.db"
    database.touch()
    connections = []

    class BulkConnection(FakeConnection):
        def execute(self, statement, params):
            self.calls.append((statement, params))
            paths = set(params[len(rekordbox_cues.HOT_CUE_SLOTS):])
            rows = []
            if "/music/a.mp3" in paths:
                rows.extend([
                    ("/music/a.mp3", "content-a", 1, 100, "A intro"),
                    ("/music/a.mp3", "content-a", 5, 4100, "A drop"),
                ])
            if "/music/empty.mp3" in paths:
                rows.append(("/music/empty.mp3", "content-empty", None, None, None))
            return FakeRows(rows)

    connection = BulkConnection()
    def connect(_):
        connections.append(connection)
        return connection
    monkeypatch.setattr(rekordbox_cues, "connect_readonly", connect)
    monkeypatch.setattr(rekordbox_cues, "PATH_BATCH_SIZE", 2)

    result = rekordbox_cues.read_hot_cues_bulk([
        "/music/a.mp3", "/music/empty.mp3", "/music/missing.mp3",
    ], database)

    assert len(connections) == 1
    assert len(connection.calls) == 2
    assert [cue.slot for cue in result.cues_by_path["/music/a.mp3"]] == [0, 3]
    assert result.cues_by_path["/music/empty.mp3"] == []
    assert "/music/missing.mp3" not in result.cues_by_path
    assert connection.closed is True


def test_import_persists_cues_and_preserves_owned_loops_and_grid(client, session, monkeypatch):
    track = _track(session)
    url = f"/api/tracks/{track.id}/performance-metadata"
    saved = client.put(url, json={
        "revision": 0,
        "cue_points": [{"slot": 2, "position_ms": 3000}],
        "loops": [{"id": "keep", "start_ms": 1000, "end_ms": 5000}],
        "beat_grid": {"bpm": 128, "first_beat_ms": 250},
    }).json()
    monkeypatch.setattr(rekordbox_cues, "read_hot_cues", lambda _: [
        CuePoint(slot=0, position_ms=500, label="Intro"),
        CuePoint(slot=7, position_ms=9000, label="Outro"),
    ])

    imported = client.post(
        f"/api/tracks/{track.id}/cues-rekordbox",
        json={"revision": saved["revision"]},
    )

    assert imported.status_code == 200, imported.text
    body = imported.json()
    assert body["revision"] == 2
    assert body["cue_points"] == [
        {"slot": 0, "position_ms": 500, "label": "Intro", "color": None},
        {"slot": 7, "position_ms": 9000, "label": "Outro", "color": None},
    ]
    assert body["loops"] == saved["loops"]
    assert body["beat_grid"] == saved["beat_grid"]
    assert client.get(url).json() == body


def test_import_rejects_stale_revision_without_mutation(client, session, monkeypatch):
    track = _track(session)
    url = f"/api/tracks/{track.id}/performance-metadata"
    before = client.put(url, json={
        "revision": 0,
        "cue_points": [{"slot": 2, "position_ms": 3000}],
    }).json()
    monkeypatch.setattr(rekordbox_cues, "read_hot_cues", lambda _: [
        CuePoint(slot=0, position_ms=500),
    ])

    response = client.post(
        f"/api/tracks/{track.id}/cues-rekordbox",
        json={"revision": 0},
    )

    assert response.status_code == 409
    assert response.json()["detail"]["current_revision"] == 1
    assert client.get(url).json() == before


def test_import_reports_unmatched_rekordbox_track_without_clearing_cues(
    client, session, monkeypatch,
):
    track = _track(session)
    url = f"/api/tracks/{track.id}/performance-metadata"
    before = client.put(url, json={
        "revision": 0,
        "cue_points": [{"slot": 2, "position_ms": 3000}],
    }).json()

    def missing(_):
        raise rekordbox_cues.RekordboxCueTrackNotFoundError("No exact match")

    monkeypatch.setattr(rekordbox_cues, "read_hot_cues", missing)
    response = client.post(
        f"/api/tracks/{track.id}/cues-rekordbox",
        json={"revision": before["revision"]},
    )

    assert response.status_code == 404
    assert client.get(url).json() == before


def test_bulk_import_counts_matches_skips_and_failures_and_preserves_unmatched(
    client, session, monkeypatch,
):
    matched = _track(session)
    unmatched = Track(filepath="/performance/unmatched.mp3", title="Unmatched", duration=180)
    failed_track = Track(filepath="/performance/failed.mp3", title="Failed", duration=180)
    session.add(unmatched)
    session.add(failed_track)
    session.commit()
    session.refresh(unmatched)
    session.refresh(failed_track)
    unmatched_before = client.put(
        f"/api/tracks/{unmatched.id}/performance-metadata",
        json={"revision": 0, "cue_points": [{"slot": 1, "position_ms": 2000}]},
    ).json()
    monkeypatch.setattr(rekordbox_cues, "read_hot_cues_bulk", lambda _: (
        rekordbox_cues.RekordboxCueBulkResult(
            cues_by_path={matched.filepath: [CuePoint(slot=0, position_ms=500)]},
            errors_by_path={failed_track.filepath: "Invalid rekordbox cue"},
        )
    ))

    response = client.post("/api/tracks/cues-rekordbox/import", json={})

    assert response.status_code == 200, response.text
    assert response.json() == {
        "imported": 1,
        "skipped": 1,
        "failed": 1,
        "conflicts": 0,
        "errors": [{"track_id": failed_track.id, "message": "Invalid rekordbox cue"}],
        "errors_truncated": 0,
    }
    session.rollback()
    assert client.get(f"/api/tracks/{matched.id}/performance-metadata").json()["cue_points"][0]["position_ms"] == 500
    assert client.get(f"/api/tracks/{unmatched.id}/performance-metadata").json() == unmatched_before


def test_bulk_import_matched_empty_source_clears_existing_cues(client, session, monkeypatch):
    track = _track(session)
    before = client.put(
        f"/api/tracks/{track.id}/performance-metadata",
        json={"revision": 0, "cue_points": [{"slot": 1, "position_ms": 2000}]},
    ).json()
    monkeypatch.setattr(rekordbox_cues, "read_hot_cues_bulk", lambda _: (
        rekordbox_cues.RekordboxCueBulkResult(cues_by_path={track.filepath: []})
    ))

    response = client.post("/api/tracks/cues-rekordbox/import", json={})

    assert response.json()["imported"] == 1
    session.rollback()
    after = client.get(f"/api/tracks/{track.id}/performance-metadata").json()
    assert after["revision"] == before["revision"] + 1
    assert after["cue_points"] == []


def test_bulk_import_reports_concurrent_revision_conflict(client, session, monkeypatch):
    track = _track(session)
    first = client.put(
        f"/api/tracks/{track.id}/performance-metadata",
        json={"revision": 0, "cue_points": [{"slot": 1, "position_ms": 2000}]},
    ).json()

    def source_after_concurrent_write(_):
        with Session(db_connection.engine) as concurrent_session:
            PerformanceMetadataAppService(concurrent_session).replace(
                track.id,
                PerformanceMetadataWrite(
                    revision=first["revision"],
                    cue_points=[{"slot": 2, "position_ms": 3000}],
                ),
            )
        return rekordbox_cues.RekordboxCueBulkResult(
            cues_by_path={track.filepath: [CuePoint(slot=0, position_ms=500)]}
        )

    monkeypatch.setattr(rekordbox_cues, "read_hot_cues_bulk", source_after_concurrent_write)
    response = client.post("/api/tracks/cues-rekordbox/import", json={})

    assert response.status_code == 200
    assert response.json()["imported"] == 0
    assert response.json()["conflicts"] == 1, response.json()
    assert response.json()["failed"] == 0
    session.rollback()
    assert client.get(f"/api/tracks/{track.id}/performance-metadata").json()["cue_points"] == [
        {"slot": 2, "position_ms": 3000, "label": "", "color": None}
    ]


def test_bulk_import_observes_edit_after_previous_track_save(client, session, monkeypatch):
    first_track = _track(session)
    second_track = Track(filepath="/performance/second.mp3", title="Second", duration=180)
    session.add(second_track)
    session.commit()
    session.refresh(second_track)
    for track in (first_track, second_track):
        client.put(
            f"/api/tracks/{track.id}/performance-metadata",
            json={"revision": 0, "cue_points": [{"slot": 1, "position_ms": 2000}]},
        )
    monkeypatch.setattr(rekordbox_cues, "read_hot_cues_bulk", lambda _: (
        rekordbox_cues.RekordboxCueBulkResult(cues_by_path={
            first_track.filepath: [CuePoint(slot=0, position_ms=500)],
            second_track.filepath: [CuePoint(slot=0, position_ms=600)],
        })
    ))
    original_replace = PerformanceMetadataAppService.replace
    injected = False

    def replace_then_edit_second(service, track_id, request):
        nonlocal injected
        result = original_replace(service, track_id, request)
        if track_id == first_track.id and not injected:
            injected = True
            with Session(db_connection.engine) as concurrent_session:
                original_replace(
                    PerformanceMetadataAppService(concurrent_session),
                    second_track.id,
                    PerformanceMetadataWrite(
                        revision=1,
                        cue_points=[{"slot": 2, "position_ms": 3000}],
                    ),
                )
        return result

    monkeypatch.setattr(PerformanceMetadataAppService, "replace", replace_then_edit_second)

    response = client.post("/api/tracks/cues-rekordbox/import", json={})

    assert response.status_code == 200, response.text
    assert response.json()["imported"] == 1
    assert response.json()["conflicts"] == 1


def test_bulk_import_without_rekordbox_source_is_404_and_does_not_mutate(
    client, session, monkeypatch,
):
    track = _track(session)
    before = client.put(
        f"/api/tracks/{track.id}/performance-metadata",
        json={"revision": 0, "cue_points": [{"slot": 1, "position_ms": 2000}]},
    ).json()
    monkeypatch.setattr(
        rekordbox_cues,
        "read_hot_cues_bulk",
        lambda _: (_ for _ in ()).throw(
            rekordbox_cues.RekordboxCueTrackNotFoundError("Library unavailable")
        ),
    )

    response = client.post("/api/tracks/cues-rekordbox/import", json={})

    assert response.status_code == 404
    assert client.get(f"/api/tracks/{track.id}/performance-metadata").json() == before
