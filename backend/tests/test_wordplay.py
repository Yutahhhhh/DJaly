import pytest
import duckdb
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlmodel import Session, create_engine, select

from domain.models.track import Track
from domain.models.wordplay import WordplayPair
from mcp_server.tools.wordplay import propose_wordplay_pairs
import infra.database.compaction as compaction
from infra.database.compaction import ensure_healthy_db
from infra.database.schema import get_schema_statements, init_raw_db


def _track(session: Session, path: str, title: str, bpm: float = 120) -> Track:
    track = Track(
        filepath=path,
        title=title,
        artist="Artist",
        album="Album",
        genre="House",
        bpm=bpm,
        duration=180,
    )
    session.add(track)
    session.commit()
    session.refresh(track)
    return track


def _proposal(from_track: Track, to_track: Track, **overrides):
    data = {
        "from_track_id": from_track.id,
        "to_track_id": to_track.id,
        "keyword": "Tonight",
        "source_phrase": "we own tonight",
        "target_phrase": "tonight we dance",
        "source_section_position": "end",
        "target_section_position": "start",
        "from_timestamp": 62.5,
        "to_timestamp": 4.0,
        "target_intro_timestamp": 0.5,
        "transition_notes": "Loop the final bar",
        "source_url": "https://example.com/evidence",
        "evidence_type": "performance",
        "verification_status": "unverified",
    }
    data.update(overrides)
    return data


def test_persistent_propose_list_review_and_verification(client: TestClient, session: Session):
    source = _track(session, "/wordplay/source.mp3", "Source")
    target = _track(session, "/wordplay/target.mp3", "Target")

    created = client.post("/api/wordplay-pairs", json=_proposal(source, target))
    assert created.status_code == 200
    item = created.json()
    assert item["status"] == "pending"
    assert item["verification_status"] == "unverified"
    assert item["source_section_position"] == "end"
    assert item["target_section_position"] == "start"
    assert item["source_cue_mode"] == "section_end"
    assert item["target_intro_timestamp"] == 0.5
    assert item["target_landing_timestamp"] == 4.0
    assert item["boundary_fit"] is True
    assert item["bpm_delta_percent"] == pytest.approx(0)
    assert item["from_track"]["title"] == "Source"
    assert item["to_track"]["title"] == "Target"
    assert "normalized_keyword" not in item

    listed = client.get(
        "/api/wordplay-pairs",
        params={"status": "pending", "from_track_id": source.id, "query": "target"},
    )
    assert listed.status_code == 200
    assert listed.json()["total"] == 1

    approved = client.post(f"/api/wordplay-pairs/{item['id']}/approve")
    assert approved.status_code == 200
    assert approved.json()["status"] == "approved"
    assert approved.json()["verification_status"] == "unverified"

    tested = client.patch(
        f"/api/wordplay-pairs/{item['id']}",
        json={"verification_status": "tested"},
    )
    assert tested.status_code == 200
    assert tested.json()["status"] == "approved"
    assert tested.json()["verification_status"] == "tested"

    edited = client.patch(
        f"/api/wordplay-pairs/{item['id']}",
        json={"transition_notes": "Corrected cue"},
    )
    assert edited.status_code == 200
    assert edited.json()["status"] == "pending"
    assert edited.json()["verification_status"] == "tested"

    transition_edit = client.patch(
        f"/api/wordplay-pairs/{item['id']}",
        json={"source_section_position": "middle", "verification_status": "tested"},
    )
    assert transition_edit.status_code == 200
    assert transition_edit.json()["status"] == "pending"
    assert transition_edit.json()["verification_status"] == "unverified"
    assert transition_edit.json()["boundary_fit"] is False


@pytest.mark.parametrize(
    "proposal_changes,target_bpm",
    [
        ({"source_section_position": "unknown"}, 120),
        ({"target_section_position": "middle"}, 120),
        ({"from_timestamp": None}, 120),
        ({"to_timestamp": None}, 120),
        ({}, 123),
    ],
)
def test_pending_approval_requires_complete_boundary_fit(
    client: TestClient,
    session: Session,
    proposal_changes,
    target_bpm,
):
    source = _track(session, "/wordplay/gate-source.mp3", "Source", bpm=120)
    target = _track(session, "/wordplay/gate-target.mp3", "Target", bpm=target_bpm)
    created = client.post(
        "/api/wordplay-pairs",
        json=_proposal(source, target, **proposal_changes),
    )
    assert created.status_code == 200
    assert created.json()["boundary_fit"] is False

    approval = client.post(f"/api/wordplay-pairs/{created.json()['id']}/approve")
    assert approval.status_code == 422
    assert "usable source cue" in approval.json()["detail"]
    assert client.get("/api/wordplay-pairs", params={"status": "pending"}).json()["total"] == 1


def test_actual_track_bpm_delta_is_computed_and_two_percent_or_less_is_approved(
    client: TestClient,
    session: Session,
):
    source = _track(session, "/wordplay/bpm-source.mp3", "Source", bpm=120)
    target = _track(session, "/wordplay/bpm-target.mp3", "Target", bpm=122.4)
    created = client.post("/api/wordplay-pairs", json=_proposal(source, target)).json()
    assert created["bpm_delta_percent"] == pytest.approx(2.0)
    assert created["boundary_fit"] is True
    approved = client.post(f"/api/wordplay-pairs/{created['id']}/approve")
    assert approved.status_code == 200
    assert approved.json()["status"] == "approved"


def test_style_fit_normalizes_exact_genre_and_subgenre(
    client: TestClient,
    session: Session,
):
    source = _track(session, "/wordplay/style-subgenre-source.mp3", "Source")
    target = _track(session, "/wordplay/style-subgenre-target.mp3", "Target")
    source.genre, target.genre = " House ", "house"
    source.subgenre, target.subgenre = "Afro House", " afro house "
    source.energy = source.danceability = source.brightness = source.noisiness = 0.0
    target.energy = target.danceability = target.brightness = target.noisiness = 1.0
    session.add(source)
    session.add(target)
    session.commit()

    created = client.post("/api/wordplay-pairs", json=_proposal(source, target))
    assert created.status_code == 200
    assert created.json()["style_fit"] is True
    assert created.json()["boundary_fit"] is True


def test_style_fit_accepts_close_features_when_subgenres_differ(
    client: TestClient,
    session: Session,
):
    source = _track(session, "/wordplay/style-features-source.mp3", "Source")
    target = _track(session, "/wordplay/style-features-target.mp3", "Target")
    source.subgenre, target.subgenre = "Deep House", "Tech House"
    source.energy, target.energy = 0.70, 0.90
    source.danceability, target.danceability = 0.80, 0.65
    source.brightness, target.brightness = 0.50, 0.68
    source.noisiness, target.noisiness = 0.20, 0.35
    session.add(source)
    session.add(target)
    session.commit()

    created = client.post("/api/wordplay-pairs", json=_proposal(source, target))
    assert created.status_code == 200
    assert created.json()["style_fit"] is True
    assert created.json()["boundary_fit"] is True


@pytest.mark.parametrize("different_genre", [True, False])
def test_style_mismatch_blocks_pending_approval(
    client: TestClient,
    session: Session,
    different_genre: bool,
):
    source = _track(session, f"/wordplay/style-bad-source-{different_genre}.mp3", "Source")
    target = _track(session, f"/wordplay/style-bad-target-{different_genre}.mp3", "Target")
    if different_genre:
        target.genre = "Hip-Hop"
    else:
        source.subgenre, target.subgenre = "Deep House", "Tech House"
        source.energy, target.energy = 0.10, 0.80
    session.add(source)
    session.add(target)
    session.commit()

    created = client.post("/api/wordplay-pairs", json=_proposal(source, target))
    assert created.status_code == 200
    assert created.json()["style_fit"] is False
    assert created.json()["boundary_fit"] is False
    approval = client.post(f"/api/wordplay-pairs/{created.json()['id']}/approve")
    assert approval.status_code == 422
    assert "compatible musical style" in approval.json()["detail"]


def test_cue_drumming_intro_can_land_on_middle_section(
    client: TestClient,
    session: Session,
):
    source = _track(session, "/wordplay/cue-drum-source.mp3", "Source", bpm=100)
    target = _track(session, "/wordplay/cue-drum-target.mp3", "Target", bpm=102)
    proposal = _proposal(
        source,
        target,
        source_cue_mode="cue_drumming_intro",
        source_section_position="middle",
        target_section_position="middle",
        from_timestamp=61.0,
        source_cue_end_timestamp=62.25,
        to_timestamp=12.0,
        target_intro_timestamp=4.0,
        target_landing_timestamp=12.0,
    )

    created = client.post("/api/wordplay-pairs", json=proposal)
    assert created.status_code == 200
    assert created.json()["source_cue_fit"] is True
    assert created.json()["target_timing_fit"] is True
    assert created.json()["boundary_fit"] is True
    approved = client.post(f"/api/wordplay-pairs/{created.json()['id']}/approve")
    assert approved.status_code == 200


@pytest.mark.parametrize(
    "changes",
    [
        {"source_cue_end_timestamp": 62.5},
        {"source_cue_end_timestamp": 61.0},
        {"target_intro_timestamp": 12.0},
        {"target_intro_timestamp": 13.0},
    ],
)
def test_cue_drumming_approval_requires_ordered_source_and_target_windows(
    client: TestClient,
    session: Session,
    changes,
):
    source = _track(session, f"/wordplay/cue-window-source-{changes}.mp3", "Source")
    target = _track(session, f"/wordplay/cue-window-target-{changes}.mp3", "Target")
    proposal = _proposal(
        source,
        target,
        source_cue_mode="cue_drumming_intro",
        source_section_position="middle",
        target_section_position="middle",
        from_timestamp=62.5,
        source_cue_end_timestamp=None,
        to_timestamp=12.0,
        target_intro_timestamp=None,
    )
    proposal.update(changes)

    created = client.post("/api/wordplay-pairs", json=proposal)
    if created.status_code == 422:
        return
    assert created.json()["boundary_fit"] is False
    approval = client.post(f"/api/wordplay-pairs/{created.json()['id']}/approve")
    assert approval.status_code == 422


def test_target_landing_timestamp_and_legacy_to_timestamp_are_aliases(
    client: TestClient,
    session: Session,
):
    source = _track(session, "/wordplay/alias-source.mp3", "Source")
    target = _track(session, "/wordplay/alias-target.mp3", "Target")
    proposal = _proposal(source, target)
    proposal.pop("to_timestamp")
    proposal["target_landing_timestamp"] = 7.5

    created = client.post("/api/wordplay-pairs", json=proposal)
    assert created.status_code == 200
    assert created.json()["to_timestamp"] == 7.5
    assert created.json()["target_landing_timestamp"] == 7.5

    updated = client.patch(
        f"/api/wordplay-pairs/{created.json()['id']}",
        json={"to_timestamp": 9.0},
    )
    assert updated.status_code == 200
    assert updated.json()["to_timestamp"] == 9.0
    assert updated.json()["target_landing_timestamp"] == 9.0

    conflict = client.patch(
        f"/api/wordplay-pairs/{created.json()['id']}",
        json={"to_timestamp": 9.0, "target_landing_timestamp": 10.0},
    )
    assert conflict.status_code == 422


@pytest.mark.parametrize(
    "timestamp_field,timestamp",
    [
        ("from_timestamp", 180),
        ("to_timestamp", 180.01),
    ],
)
def test_create_rejects_cue_at_or_after_track_duration(
    client: TestClient,
    session: Session,
    timestamp_field,
    timestamp,
):
    source = _track(session, "/wordplay/range-source.mp3", "Source")
    target = _track(session, "/wordplay/range-target.mp3", "Target")
    response = client.post(
        "/api/wordplay-pairs",
        json=_proposal(source, target, **{timestamp_field: timestamp}),
    )
    assert response.status_code == 422
    assert "before the selected track duration" in response.json()["detail"]


def test_update_rejects_out_of_range_cue_without_mutating_review(client: TestClient, session: Session):
    source = _track(session, "/wordplay/update-range-source.mp3", "Source")
    target = _track(session, "/wordplay/update-range-target.mp3", "Target")
    created = client.post("/api/wordplay-pairs", json=_proposal(source, target)).json()
    assert client.post(f"/api/wordplay-pairs/{created['id']}/approve").status_code == 200

    response = client.patch(
        f"/api/wordplay-pairs/{created['id']}",
        json={"to_timestamp": 180},
    )
    assert response.status_code == 422
    persisted = client.get("/api/wordplay-pairs", params={"status": "approved"}).json()["items"][0]
    assert persisted["to_timestamp"] == 4.0
    assert persisted["boundary_fit"] is True


def test_persisted_out_of_range_legacy_cue_is_never_boundary_fit(client: TestClient, session: Session):
    source = _track(session, "/wordplay/legacy-range-source.mp3", "Source")
    target = _track(session, "/wordplay/legacy-range-target.mp3", "Target")
    pair = WordplayPair(
        from_track_id=source.id,
        to_track_id=target.id,
        keyword="legacy range",
        normalized_keyword="legacy range",
        source_phrase="out",
        target_phrase="in",
        source_section_position="end",
        target_section_position="start",
        from_timestamp=source.duration,
        to_timestamp=0,
        status="approved",
    )
    session.add(pair)
    session.commit()

    item = client.get("/api/wordplay-pairs").json()["items"][0]
    assert item["from_timestamp"] == source.duration
    assert item["boundary_fit"] is False


def test_legacy_approved_pair_is_not_invalidated_by_boundary_gate(client: TestClient, session: Session):
    source = _track(session, "/wordplay/legacy-source.mp3", "Source")
    target = _track(session, "/wordplay/legacy-target.mp3", "Target")
    pair = WordplayPair(
        from_track_id=source.id,
        to_track_id=target.id,
        keyword="legacy",
        normalized_keyword="legacy",
        source_phrase="legacy out",
        target_phrase="legacy in",
        status="approved",
    )
    session.add(pair)
    session.commit()
    session.refresh(pair)

    response = client.post(f"/api/wordplay-pairs/{pair.id}/approve")
    assert response.status_code == 200
    assert response.json()["status"] == "approved"
    assert response.json()["boundary_fit"] is False


@pytest.mark.parametrize(
    "field,value",
    [
        ("from_track_id", True),
        ("to_track_id", False),
        ("from_timestamp", True),
        ("to_timestamp", False),
    ],
)
def test_create_rejects_boolean_numeric_fields(client: TestClient, session: Session, field, value):
    source = _track(session, "/wordplay/strict-source.mp3", "Source")
    target = _track(session, "/wordplay/strict-target.mp3", "Target")
    response = client.post(
        "/api/wordplay-pairs",
        json=_proposal(source, target, **{field: value}),
    )
    assert response.status_code == 422


@pytest.mark.parametrize("changes", [{"from_track_id": True}, {"to_timestamp": False}])
def test_update_rejects_boolean_numeric_fields(client: TestClient, session: Session, changes):
    source = _track(session, "/wordplay/strict-update-source.mp3", "Source")
    target = _track(session, "/wordplay/strict-update-target.mp3", "Target")
    pair_id = client.post("/api/wordplay-pairs", json=_proposal(source, target)).json()["id"]
    assert client.patch(f"/api/wordplay-pairs/{pair_id}", json=changes).status_code == 422


def test_create_accepts_integer_and_decimal_timestamps(client: TestClient, session: Session):
    source = _track(session, "/wordplay/numeric-source.mp3", "Source")
    target = _track(session, "/wordplay/numeric-target.mp3", "Target")
    response = client.post(
        "/api/wordplay-pairs",
        json=_proposal(source, target, from_timestamp=62, to_timestamp=4.5),
    )
    assert response.status_code == 200
    assert response.json()["from_timestamp"] == 62
    assert response.json()["to_timestamp"] == 4.5


def test_directional_dedup_preserves_reviewed_pair(client: TestClient, session: Session):
    first = _track(session, "/wordplay/a.mp3", "A")
    second = _track(session, "/wordplay/b.mp3", "B")
    original = client.post("/api/wordplay-pairs", json=_proposal(first, second)).json()
    client.post(f"/api/wordplay-pairs/{original['id']}/approve")

    duplicate = client.post(
        "/api/wordplay-pairs",
        json=_proposal(
            first,
            second,
            keyword="  TONIGHT  ",
            transition_notes="must not overwrite reviewed metadata",
        ),
    )
    assert duplicate.status_code == 200
    assert duplicate.json()["id"] == original["id"]
    assert duplicate.json()["status"] == "approved"
    assert duplicate.json()["transition_notes"] == "Loop the final bar"

    reversed_pair = client.post("/api/wordplay-pairs", json=_proposal(second, first))
    assert reversed_pair.status_code == 200
    assert reversed_pair.json()["id"] != original["id"]
    assert client.get("/api/wordplay-pairs").json()["total"] == 2


def test_reject_deletes_only_pair(client: TestClient, session: Session):
    source = _track(session, "/wordplay/keep-source.mp3", "Keep Source")
    target = _track(session, "/wordplay/keep-target.mp3", "Keep Target")
    pair_id = client.post("/api/wordplay-pairs", json=_proposal(source, target)).json()["id"]

    rejected = client.delete(f"/api/wordplay-pairs/{pair_id}")
    assert rejected.status_code == 200
    assert session.get(WordplayPair, pair_id) is None
    assert session.get(Track, source.id) is not None
    assert session.get(Track, target.id) is not None


def test_approval_rejects_pair_with_dangling_track(client: TestClient, session: Session):
    source = _track(session, "/wordplay/dangling-source.mp3", "Source")
    target = _track(session, "/wordplay/dangling-target.mp3", "Target")
    pair_id = client.post("/api/wordplay-pairs", json=_proposal(source, target)).json()["id"]
    session.delete(target)
    session.commit()

    approval = client.post(f"/api/wordplay-pairs/{pair_id}/approve")
    assert approval.status_code == 404
    session.expire_all()
    assert session.get(WordplayPair, pair_id).status == "pending"
    assert client.delete(f"/api/wordplay-pairs/{pair_id}").status_code == 200


def test_atomic_batch_rolls_back_when_any_proposal_is_invalid(session: Session):
    source = _track(session, "/wordplay/batch-source.mp3", "Batch Source")
    target = _track(session, "/wordplay/batch-target.mp3", "Batch Target")
    with pytest.raises(ValueError):
        propose_wordplay_pairs([
            _proposal(source, target, keyword="valid"),
            _proposal(source, target, keyword="blank", source_url="ftp://bad"),
        ])

    session.rollback()
    session.expire_all()
    assert session.exec(select(WordplayPair)).all() == []


def test_wordplay_pairs_survive_database_compaction(tmp_path, monkeypatch):
    path = str(tmp_path / "wordplay-compaction.duckdb")
    connection = duckdb.connect(path)
    for statement in get_schema_statements():
        connection.execute(statement)
    connection.execute("INSERT INTO tracks (filepath, title) VALUES ('/from.mp3', 'From')")
    connection.execute("INSERT INTO tracks (filepath, title) VALUES ('/to.mp3', 'To')")
    connection.execute(
        "INSERT INTO wordplay_pairs "
        "(from_track_id, to_track_id, keyword, normalized_keyword, source_phrase, target_phrase) "
        "VALUES (1, 2, 'Night', 'night', 'good night', 'night begins')"
    )
    connection.execute(
        "INSERT INTO schema_info VALUES ('version', '4') "
        "ON CONFLICT (key) DO UPDATE SET value=excluded.value"
    )
    connection.close()

    monkeypatch.setattr(compaction, "COMPACT_MIN_BYTES", 1)
    monkeypatch.setattr(compaction, "COMPACT_BYTES_PER_TRACK", 1)
    monkeypatch.setattr(compaction, "COMPACT_RATIO_LIMIT", 1)
    ensure_healthy_db(path)

    rebuilt = duckdb.connect(path)
    try:
        row = rebuilt.execute(
            "SELECT from_track_id, to_track_id, keyword, status FROM wordplay_pairs"
        ).fetchone()
        assert row == (1, 2, "Night", "pending")
        rebuilt.execute(
            "INSERT INTO wordplay_pairs "
            "(from_track_id, to_track_id, keyword, normalized_keyword, source_phrase, target_phrase) "
            "VALUES (2, 1, 'Night', 'night', 'night begins', 'good night')"
        )
        assert rebuilt.execute("SELECT MAX(id) FROM wordplay_pairs").fetchone()[0] == 2
    finally:
        rebuilt.close()


def test_existing_v4_wordplay_table_gets_unknown_boundary_defaults(tmp_path):
    path = str(tmp_path / "legacy-wordplay-v4.duckdb")
    legacy = duckdb.connect(path)
    legacy.execute("CREATE SEQUENCE seq_wordplay_pairs_id START 2")
    legacy.execute(
        "CREATE TABLE wordplay_pairs ("
        "id INTEGER PRIMARY KEY DEFAULT nextval('seq_wordplay_pairs_id'), "
        "from_track_id INTEGER NOT NULL, to_track_id INTEGER NOT NULL, "
        "keyword VARCHAR NOT NULL, normalized_keyword VARCHAR NOT NULL, "
        "source_phrase VARCHAR NOT NULL, target_phrase VARCHAR NOT NULL, "
        "from_timestamp DOUBLE, to_timestamp DOUBLE, "
        "transition_notes VARCHAR NOT NULL DEFAULT '', source_url VARCHAR NOT NULL DEFAULT '', "
        "evidence_type VARCHAR NOT NULL DEFAULT 'hypothesis', "
        "verification_status VARCHAR NOT NULL DEFAULT 'unverified', "
        "status VARCHAR NOT NULL DEFAULT 'pending', "
        "created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, "
        "UNIQUE (from_track_id, to_track_id, normalized_keyword))"
    )
    legacy.execute(
        "INSERT INTO wordplay_pairs "
        "(id, from_track_id, to_track_id, keyword, normalized_keyword, source_phrase, target_phrase, status) "
        "VALUES (1, 10, 20, 'legacy', 'legacy', 'out', 'in', 'approved')"
    )
    legacy.execute("CREATE TABLE schema_info (key VARCHAR PRIMARY KEY, value VARCHAR NOT NULL)")
    legacy.execute("INSERT INTO schema_info VALUES ('version', '4')")
    legacy.close()

    engine = create_engine(f"duckdb:///{path}")
    try:
        init_raw_db(engine)
        with engine.connect() as connection:
            row = connection.execute(
                text(
                    "SELECT source_section_position, target_section_position, source_cue_mode, "
                    "source_cue_end_timestamp, target_intro_timestamp, target_landing_timestamp, status "
                    "FROM wordplay_pairs WHERE id=1"
                )
            ).fetchone()
            assert row == ("unknown", "unknown", "section_end", None, None, None, "approved")
    finally:
        engine.dispose()


@pytest.mark.parametrize(
    "payload, expected_status",
    [
        ({"same_track": True}, 422),
        ({"from_track_id": 999999}, 404),
        ({"source_url": "file:///tmp/evidence"}, 422),
        ({"from_timestamp": -0.1}, 422),
    ],
)
def test_proposal_boundary_validation(
    client: TestClient,
    session: Session,
    payload,
    expected_status,
):
    source = _track(session, f"/wordplay/validation-source-{expected_status}-{len(payload)}.mp3", "Source")
    target = _track(session, f"/wordplay/validation-target-{expected_status}-{len(payload)}.mp3", "Target")
    request = _proposal(source, target)
    if payload.pop("same_track", False):
        request["to_track_id"] = source.id
    request.update(payload)
    assert client.post("/api/wordplay-pairs", json=request).status_code == expected_status
