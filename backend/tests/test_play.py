from datetime import datetime
import unicodedata

from sqlalchemy import event, text

from domain.models.track import Track


def _track(session, filepath="/music/a.wav"):
    track = Track(filepath=filepath, title="A", artist="DJ", genre="House", bpm=128, key="8A", duration=180)
    session.add(track)
    session.commit()
    session.refresh(track)
    return track


def test_rekordbox_mirror_preserves_tree_order_and_is_idempotent(client, session):
    track = _track(session)
    payload = {
        "source_id": "rb-main", "source_name": "Rekordbox",
        "playlists": [
            {"external_id": "folder", "name": "Sets", "kind": "folder", "order": 1},
            {"external_id": "night", "parent_external_id": "folder", "name": "Night", "kind": "playlist", "order": 2},
        ],
        "members": [
            {"playlist_external_id": "night", "position": 2, "external_track_id": "missing", "title": "Missing"},
            {"playlist_external_id": "night", "position": 1, "external_track_id": "mapped", "local_track_id": track.id},
        ],
    }
    first = client.post("/api/play/rekordbox/import", json=payload)
    assert first.status_code == 200
    assert first.json()["resolved"] == 1
    assert client.post("/api/play/rekordbox/import", json=payload).status_code == 200
    tree = client.get("/api/play/rekordbox/rb-main/tree").json()["items"]
    assert [(p["external_id"], p["parent_external_id"]) for p in tree] == [("folder", None), ("night", "folder")]
    assert tree[0]["track_count"] == 0 and tree[0]["unmapped_count"] == 0
    assert tree[1]["track_count"] == 2 and tree[1]["unmapped_count"] == 1
    rows = client.get("/api/play/rekordbox/rb-main/playlists/night/tracks").json()
    assert [row["position"] for row in rows] == [1, 2]
    assert rows[0]["resolved"] is True and rows[0]["local_track_id"] == track.id
    assert rows[1]["resolved"] is False


def test_mirror_rejects_broken_hierarchy(client):
    response = client.post("/api/play/rekordbox/import", json={
        "source_id": "bad", "source_name": "Bad",
        "playlists": [{"external_id": "child", "parent_external_id": "missing", "name": "Child"}],
    })
    assert response.status_code == 400


def test_mirror_indexes_library_once_and_matches_unicode_and_symlink_paths(client, session, tmp_path):
    audio = tmp_path / "caf\u00e9.wav"
    audio.touch()
    alias = tmp_path / "alias.wav"
    alias.symlink_to(audio)
    track = _track(session, str(audio))
    library_reads = []

    def record_query(connection, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith("SELECT") and "FROM tracks" in statement:
            library_reads.append(statement)

    engine = session.get_bind()
    event.listen(engine, "before_cursor_execute", record_query)
    try:
        result = client.post("/api/play/rekordbox/import", json={
            "source_id": "paths", "source_name": "Paths",
            "playlists": [{"external_id": "p", "name": "P"}],
            "members": [
                {"playlist_external_id": "p", "position": 1, "filepath": str(alias)},
                {"playlist_external_id": "p", "position": 2,
                 "filepath": unicodedata.normalize("NFD", str(audio)), "local_track_id": 999999},
                {"playlist_external_id": "p", "position": 3, "filepath": str(alias)},
                {"playlist_external_id": "p", "position": 4, "filepath": "/missing.wav"},
            ],
        })
    finally:
        event.remove(engine, "before_cursor_execute", record_query)
    assert result.status_code == 200
    assert result.json()["resolved"] == 3
    assert result.json()["unmapped"] == 1
    assert len(library_reads) == 1
    rows = client.get("/api/play/rekordbox/paths/playlists/p/tracks").json()
    assert [row["local_track_id"] for row in rows] == [track.id, track.id, track.id, None]
    assert rows[3]["source_filepath"] == "/missing.wav"


def test_mirror_rejects_parent_cycles_without_replacing_existing_import(client):
    valid = {
        "source_id": "cycle-source", "source_name": "Before",
        "playlists": [{"external_id": "kept", "name": "Kept"}],
    }
    assert client.post("/api/play/rekordbox/import", json=valid).status_code == 200

    cyclic = {
        "source_id": "cycle-source", "source_name": "After",
        "playlists": [
            {"external_id": "a", "parent_external_id": "b", "name": "A"},
            {"external_id": "b", "parent_external_id": "a", "name": "B"},
        ],
    }
    response = client.post("/api/play/rekordbox/import", json=cyclic)
    assert response.status_code == 422
    assert "cycle" in response.json()["detail"].lower()
    tree = client.get("/api/play/rekordbox/cycle-source/tree").json()
    assert tree["source"]["name"] == "Before"
    assert [item["external_id"] for item in tree["items"]] == ["kept"]


def test_history_and_recording_upserts_are_idempotent(client, session):
    track = _track(session)
    assert client.post("/api/play/sessions", json={"id": "session-1", "deck_count": 4}).status_code == 200
    history = {"event_key": "event-1", "session_id": "session-1", "deck": "C", "track_id": track.id, "played_ms": 100}
    assert client.put("/api/play/history", json=history).status_code == 200
    history.update({"played_ms": 1000, "completed": True, "ended_at": datetime.now().isoformat()})
    assert client.put("/api/play/history", json=history).status_code == 200
    rows = client.get("/api/play/history").json()
    assert len(rows) == 1 and rows[0]["played_ms"] == 1000 and rows[0]["deck"] == "C"

    recording = {"recording_key": "rec-1", "session_id": "session-1", "filepath": "/music/record.wav", "started_at": datetime.now().isoformat()}
    assert client.put("/api/play/recordings", json=recording).status_code == 200
    recording.update({"status": "completed", "duration_ms": 2500, "ended_at": datetime.now().isoformat()})
    assert client.put("/api/play/recordings", json=recording).status_code == 200
    recordings = client.get("/api/play/recordings").json()
    assert len(recordings) == 1 and recordings[0]["duration_ms"] == 2500


def test_restarting_session_clears_ended_at(client, session):
    payload = {"id": "session-restart", "deck_count": 2}
    assert client.post("/api/play/sessions", json=payload).status_code == 200
    assert client.post("/api/play/sessions/session-restart/end").status_code == 200
    payload["deck_count"] = 4
    assert client.post("/api/play/sessions", json=payload).status_code == 200

    row = session.exec(
        text("SELECT ended_at,deck_count FROM play_sessions WHERE id=:id"),
        params={"id": "session-restart"},
    ).first()
    assert row[0] is None and row[1] == 4


def test_late_incomplete_history_write_cannot_reopen_completed_event(client, session):
    track = _track(session)
    assert client.post("/api/play/sessions", json={"id": "history-order", "deck_count": 2}).status_code == 200
    ended_at = datetime.now().isoformat()
    completed = {
        "event_key": "event-order", "session_id": "history-order", "deck": "A", "track_id": track.id,
        "played_ms": 2400, "completed": True, "ended_at": ended_at, "reason": "track-ended",
    }
    assert client.put("/api/play/history", json=completed).status_code == 200
    late_incomplete = {
        "event_key": "event-order", "session_id": "history-order", "deck": "A", "track_id": track.id,
        "played_ms": 9000, "completed": False, "ended_at": None, "reason": "stale",
    }
    assert client.put("/api/play/history", json=late_incomplete).status_code == 200

    row = client.get("/api/play/history").json()[0]
    assert row["completed"] is True
    assert row["played_ms"] == 2400
    assert row["ended_at"] == ended_at
    assert row["reason"] == "track-ended"


def test_recording_upsert_is_monotonic_for_ordered_and_late_writes(client):
    started_at = datetime.now().isoformat()
    initial = {
        "recording_key": "rec-order", "session_id": "session-order",
        "filepath": "/music/original.wav", "started_at": started_at,
        "status": "recording", "duration_ms": 100,
    }
    assert client.put("/api/play/recordings", json=initial).status_code == 200
    completed = {**initial, "status": "completed", "duration_ms": 2500,
                 "ended_at": datetime.now().isoformat()}
    assert client.put("/api/play/recordings", json=completed).status_code == 200
    late = {**initial, "filepath": "/music/stale.wav", "duration_ms": 400,
            "status": "recording", "ended_at": None}
    assert client.put("/api/play/recordings", json=late).status_code == 200

    row = client.get("/api/play/recordings").json()[0]
    assert row["status"] == "completed"
    assert row["duration_ms"] == 2500
    assert row["filepath"] == "/music/original.wav"
    assert row["ended_at"] == completed["ended_at"]


def test_recording_duration_never_decreases_after_terminal_write(client):
    started_at = datetime.now().isoformat()
    failed = {
        "recording_key": "rec-failed", "filepath": "/music/failed.wav", "started_at": started_at,
        "status": "failed", "duration_ms": 800, "error": "disk full",
    }
    assert client.put("/api/play/recordings", json=failed).status_code == 200
    late = {**failed, "status": "recording", "duration_ms": 1200, "error": None}
    assert client.put("/api/play/recordings", json=late).status_code == 200

    row = client.get("/api/play/recordings").json()[0]
    assert row["status"] == "failed"
    assert row["duration_ms"] == 1200
    assert row["error"] == "disk full"


def _recording_row(client, tmp_path, name="mix.wav"):
    import wave, struct
    path = tmp_path / name
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(2); handle.setsampwidth(2); handle.setframerate(44100)
        handle.writeframes(struct.pack("<hh", 1000, 1000) * 4410)
    client.put("/api/play/recordings", json={
        "recording_key": f"key-{name}", "filepath": str(path),
        "started_at": "2026-09-08T17:00:00", "duration_ms": 100, "status": "completed",
    })
    rows = client.get("/api/play/recordings").json()
    return next(row for row in rows if row["recording_key"] == f"key-{name}"), path


def test_recording_can_be_previewed_named_and_discarded(client, tmp_path):
    """録音は聴いて確かめてから名前を付けて確定する。破棄は音声ごと消す。"""
    row, path = _recording_row(client, tmp_path)

    audio = client.get(f"/api/play/recordings/{row['id']}/audio")
    assert audio.status_code == 200
    assert audio.headers["content-type"] == "audio/wav"

    named = client.patch(f"/api/play/recordings/{row['id']}",
                         json={"artist": "DJ Test", "title": "Late Night"})
    assert named.status_code == 200
    renamed = tmp_path / "DJ Test - Late Night.wav"
    assert renamed.is_file() and not path.exists(), "ファイル名も保存名に合わせる"
    assert named.json()["artist"] == "DJ Test"
    assert named.json()["title"] == "Late Night"

    discarded = client.delete(f"/api/play/recordings/{row['id']}")
    assert discarded.status_code == 200
    assert not renamed.exists(), "破棄は音声ファイルも消す"
    assert all(r["recording_key"] != row["recording_key"] for r in client.get("/api/play/recordings").json())


def test_recording_preview_supports_range_requests_and_real_media_type(client, tmp_path):
    row, _ = _recording_row(client, tmp_path, "seekable.wav")
    audio = client.get(
        f"/api/play/recordings/{row['id']}/audio", headers={"Range": "bytes=0-15"},
    )
    assert audio.status_code == 206
    assert audio.headers["accept-ranges"] == "bytes"
    assert audio.headers["content-range"].startswith("bytes 0-15/")
    assert audio.headers["cache-control"] == "no-store"
    assert len(audio.content) == 16

    mp3 = tmp_path / "preview.mp3"
    mp3.write_bytes(b"ID3" + bytes(64))
    client.put("/api/play/recordings", json={
        "recording_key": "key-preview-mp3", "filepath": str(mp3),
        "started_at": "2026-09-08T17:00:00", "duration_ms": 100, "status": "completed",
    })
    mp3_row = next(row for row in client.get("/api/play/recordings").json()
                   if row["recording_key"] == "key-preview-mp3")
    assert client.get(f"/api/play/recordings/{mp3_row['id']}/audio").headers["content-type"] == "audio/mpeg"


def test_recording_formats_only_lists_detected_encoders(client, mocker):
    mocker.patch("api.routers.play._available_recording_formats", return_value=("wav", "mp3"))
    response = client.get("/api/play/recordings/formats")
    assert response.status_code == 200
    assert [item["value"] for item in response.json()["formats"]] == ["wav", "mp3"]


def test_recording_export_conversion_keeps_source_until_conversion_succeeds(client, tmp_path, mocker):
    import subprocess
    from api.routers import play

    row, source = _recording_row(client, tmp_path, "convert-me.wav")
    mocker.patch.object(play, "_ffmpeg_path", return_value="/fake/ffmpeg")
    mocker.patch.object(play, "_available_recording_formats", return_value=("wav", "flac", "mp3"))
    failed = subprocess.CompletedProcess([], 1, "", "encoder failed")
    mocker.patch.object(play.subprocess, "run", return_value=failed)

    response = client.patch(f"/api/play/recordings/{row['id']}", json={
        "artist": "DJ Test", "title": "Protected", "format": "mp3",
    })
    assert response.status_code == 422
    assert source.is_file(), "失敗した変換で唯一の元音源を消さない"
    assert not (tmp_path / "DJ Test - Protected.mp3").exists()
    current = next(item for item in client.get("/api/play/recordings").json() if item["id"] == row["id"])
    assert current["filepath"] == str(source)


def test_recording_can_be_exported_to_selected_format(client, tmp_path):
    from api.routers.play import _available_recording_formats

    if "flac" not in _available_recording_formats():
        import pytest
        pytest.skip("FFmpeg FLAC encoder is unavailable")
    row, source = _recording_row(client, tmp_path, "export-me.wav")
    response = client.patch(f"/api/play/recordings/{row['id']}", json={
        "artist": "DJ Test", "title": "Lossless", "format": "flac",
    })
    assert response.status_code == 200, response.text
    exported = tmp_path / "DJ Test - Lossless.flac"
    assert exported.is_file() and exported.stat().st_size > 0
    assert not source.exists()
    assert response.json()["filepath"] == str(exported)


def test_recording_rename_restores_source_when_database_commit_fails(client, session, tmp_path, mocker):
    import pytest
    from api.routers.play import name_recording
    from api.schemas.play import RecordingName

    row, source = _recording_row(client, tmp_path, "commit-failure.wav")
    mocker.patch.object(session, "commit", side_effect=RuntimeError("commit failed"))
    with pytest.raises(RuntimeError, match="commit failed"):
        name_recording(row["id"], RecordingName(artist="DJ Test", title="Restored"), session)
    assert source.is_file()
    assert not (tmp_path / "DJ Test - Restored.wav").exists()


def test_recording_conversion_never_overwrites_target_created_during_conversion(client, tmp_path, mocker):
    import subprocess
    from api.routers import play

    row, source = _recording_row(client, tmp_path, "conversion-race.wav")
    target = tmp_path / "DJ Test - Claimed.mp3"
    mocker.patch.object(play, "_ffmpeg_path", return_value="/fake/ffmpeg")
    mocker.patch.object(play, "_available_recording_formats", return_value=("wav", "flac", "mp3"))

    def finish_after_target_is_claimed(command, **_kwargs):
        Path = type(target)
        Path(command[-1]).write_bytes(b"converted")
        target.write_bytes(b"someone else's recording")
        return subprocess.CompletedProcess(command, 0, "", "")

    mocker.patch.object(play.subprocess, "run", side_effect=finish_after_target_is_claimed)
    response = client.patch(f"/api/play/recordings/{row['id']}", json={
        "artist": "DJ Test", "title": "Claimed", "format": "mp3",
    })
    assert response.status_code == 409
    assert target.read_bytes() == b"someone else's recording"
    assert source.is_file()


def test_recording_name_requires_a_mix_name(client, tmp_path):
    row, _ = _recording_row(client, tmp_path, "needs-name.wav")
    assert client.patch(f"/api/play/recordings/{row['id']}", json={"artist": "A", "title": "   "}).status_code == 422


def test_recording_name_refuses_to_overwrite_an_existing_file(client, tmp_path):
    first, _ = _recording_row(client, tmp_path, "one.wav")
    second, _ = _recording_row(client, tmp_path, "two.wav")
    assert client.patch(f"/api/play/recordings/{first['id']}", json={"artist": "", "title": "Same"}).status_code == 200
    clash = client.patch(f"/api/play/recordings/{second['id']}", json={"artist": "", "title": "Same"})
    assert clash.status_code == 409, "既存ファイルを黙って上書きしない"


def test_recording_rename_does_not_overwrite_late_destination(client, tmp_path, mocker):
    from api.routers import play

    row, source = _recording_row(client, tmp_path, "rename-race.wav")
    target = tmp_path / "DJ Test - Claimed.wav"
    original_link = play.os.link

    def claim_before_link(source_path, destination):
        target.write_bytes(b"another recording")
        return original_link(source_path, destination)

    mocker.patch.object(play.os, "link", side_effect=claim_before_link)
    response = client.patch(f"/api/play/recordings/{row['id']}", json={
        "artist": "DJ Test", "title": "Claimed", "format": "wav",
    })
    assert response.status_code == 409
    assert source.is_file()
    assert target.read_bytes() == b"another recording"


def test_active_recording_cannot_be_previewed_renamed_or_deleted(client, tmp_path):
    source = tmp_path / "active.wav"
    source.write_bytes(b"still recording")
    assert client.put("/api/play/recordings", json={
        "recording_key": "active-guard", "filepath": str(source),
        "started_at": datetime.now().isoformat(), "status": "recording", "duration_ms": 0,
    }).status_code == 200
    row = next(item for item in client.get("/api/play/recordings").json() if item["recording_key"] == "active-guard")
    url = f"/api/play/recordings/{row['id']}"
    assert client.get(url + "/audio").status_code == 409
    assert client.patch(url, json={"artist": "", "title": "Changed"}).status_code == 409
    assert client.delete(url).status_code == 409
    assert source.read_bytes() == b"still recording"


def test_recording_encoder_probe_recovers_after_a_failed_first_launch(mocker):
    import subprocess
    from api.routers import play

    play._probe_recording_formats.cache_clear()
    mocker.patch.object(play, "_ffmpeg_path", return_value="/probe/ffmpeg")
    run = mocker.patch.object(play.subprocess, "run", side_effect=[
        subprocess.TimeoutExpired("ffmpeg", 180),
        subprocess.CompletedProcess([], 0, "pcm_s16le flac libmp3lame", ""),
    ])
    assert play._available_recording_formats() == ()
    assert play._available_recording_formats() == ("wav", "flac", "mp3")
    assert run.call_count == 2
    play._probe_recording_formats.cache_clear()
