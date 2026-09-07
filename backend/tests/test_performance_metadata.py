from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
import threading

from sqlmodel import Session
from api.schemas.performance_metadata import PerformanceMetadataWrite
from app.services.performance_metadata_app_service import (
    PerformanceMetadataAppService,
    PerformanceMetadataConflictError,
)
from infra.database import connection as db_connection

from domain.models.track import Track


def _track(session: Session, duration: float = 180.0) -> Track:
    track = Track(
        filepath="/performance/metadata.mp3",
        title="Metadata",
        artist="DJaly",
        genre="House",
        bpm=128.0,
        key="8A",
        duration=duration,
        created_at=datetime.now(),
    )
    session.add(track)
    session.commit()
    session.refresh(track)
    return track


def test_get_returns_unpersisted_empty_metadata(client, session: Session):
    track = _track(session)

    response = client.get(f"/api/tracks/{track.id}/performance-metadata")

    assert response.status_code == 200
    assert response.json() == {
        "track_id": track.id,
        "revision": 0,
        "cue_points": [],
        "loops": [],
        "beat_grid": None,
        "created_at": None,
        "updated_at": None,
    }


def test_replace_round_trips_and_increments_revision(client, session: Session):
    track = _track(session)
    payload = {
        "revision": 0,
        "cue_points": [{"slot": 0, "position_ms": 1250, "label": "Intro", "color": "cyan"}],
        "loops": [{"id": "intro-8", "start_ms": 1250, "end_ms": 5000, "label": "Intro loop"}],
        "beat_grid": {"bpm": 128, "first_beat_ms": 312.5, "beats_per_bar": 4},
    }

    saved = client.put(f"/api/tracks/{track.id}/performance-metadata", json=payload)

    assert saved.status_code == 200
    assert saved.json()["revision"] == 1
    assert saved.json()["cue_points"] == payload["cue_points"]
    assert saved.json()["loops"] == payload["loops"]
    assert saved.json()["beat_grid"] == payload["beat_grid"]
    assert client.get(f"/api/tracks/{track.id}/performance-metadata").json() == saved.json()


def test_replace_rejects_stale_revision_without_mutation(client, session: Session):
    track = _track(session)
    url = f"/api/tracks/{track.id}/performance-metadata"
    first = client.put(url, json={"revision": 0, "cue_points": [], "loops": [], "beat_grid": None})
    assert first.status_code == 200

    stale = client.put(
        url,
        json={"revision": 0, "cue_points": [{"slot": 1, "position_ms": 1000}], "loops": []},
    )

    assert stale.status_code == 409
    assert stale.json()["detail"]["current_revision"] == 1
    assert client.get(url).json()["cue_points"] == []


def test_replace_validates_unique_slots_and_track_bounds(client, session: Session):
    track = _track(session, duration=10)
    url = f"/api/tracks/{track.id}/performance-metadata"

    duplicate = client.put(
        url,
        json={
            "revision": 0,
            "cue_points": [{"slot": 0, "position_ms": 100}, {"slot": 0, "position_ms": 200}],
            "loops": [],
        },
    )
    assert duplicate.status_code == 422

    beyond_duration = client.put(
        url,
        json={
            "revision": 0,
            "cue_points": [],
            "loops": [{"id": "too-long", "start_ms": 9000, "end_ms": 10001}],
        },
    )
    assert beyond_duration.status_code == 422


def test_missing_track_is_not_created(client):
    assert client.get("/api/tracks/999999/performance-metadata").status_code == 404
    response = client.put(
        "/api/tracks/999999/performance-metadata",
        json={"revision": 0, "cue_points": [], "loops": []},
    )
    assert response.status_code == 404


def test_concurrent_initial_replacements_resolve_to_success_and_conflict(session: Session):
    track = _track(session)
    barrier = threading.Barrier(2)

    def replace_once(slot: int):
        with Session(db_connection.engine) as worker_session:
            barrier.wait(timeout=10)
            try:
                saved = PerformanceMetadataAppService(worker_session).replace(
                    track.id,
                    PerformanceMetadataWrite(
                        revision=0,
                        cue_points=[{"slot": slot, "position_ms": 1000 + slot}],
                    ),
                )
                return ("saved", saved["revision"])
            except PerformanceMetadataConflictError as exc:
                return ("conflict", exc.current_revision)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(replace_once, [0, 1]))

    assert sorted(results) == [("conflict", 1), ("saved", 1)]
