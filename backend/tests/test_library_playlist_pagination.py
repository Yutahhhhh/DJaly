import json

import pytest
from sqlmodel import Session, text

from models import Track, TrackEmbedding
from app.services.setlist_app_service import SetlistAppService
from utils.audio_math import calculate_mixability_score
from utils.embedding import cosine_similarity


def _track(index: int, *, genre: str = "House", bpm: float = 120, key: str = "8A") -> Track:
    return Track(
        filepath=f"/pagination/{index}.mp3", title=f"Track {index:03d}", artist="Artist",
        album="Album", genre=genre, bpm=bpm, key=key, duration=180,
    )


def test_collection_page_has_exact_filtered_total_and_stable_bounds(client, session: Session):
    for index in range(12):
        session.add(_track(index, genre="House" if index < 9 else "Techno"))
    session.commit()

    response = client.get("/api/tracks/page", params={"genres": "House", "limit": 4, "offset": 4})
    assert response.status_code == 200
    page = response.json()
    assert page["total"] == 9
    assert len(page["items"]) == 4
    assert page["has_more"] is True
    assert client.get("/api/tracks/page", params={"limit": 501}).status_code == 422
    # The legacy list shape remains available.
    assert isinstance(client.get("/api/tracks", params={"limit": 2}).json(), list)


def test_collection_deep_page_over_twenty_thousand_rows(client, session: Session):
    session.exec(text("""
        INSERT INTO tracks
        (filepath,title,artist,album,genre,subgenre,bpm,key,scale,duration,energy,
         danceability,loudness,brightness,noisiness,contrast,loudness_range,
         spectral_flux,spectral_rolloff,is_genre_verified,created_at)
        SELECT '/bulk/' || i || '.mp3', 'Bulk ' || lpad(CAST(i AS VARCHAR), 5, '0'),
               'Artist','Album',CASE WHEN i % 2 = 0 THEN 'House' ELSE 'Techno' END,
               '',120,'8A','',180,0,0,-60,0,0,0,0,0,0,false,CURRENT_TIMESTAMP
        FROM range(20000) AS bulk(i)
    """))
    session.commit()
    response = client.get("/api/tracks/page", params={
        "genres": "House", "limit": 25, "offset": 9975,
    })
    assert response.status_code == 200
    page = response.json()
    assert page["total"] == 10000
    assert len(page["items"]) == 25
    assert page["offset"] == 9975
    assert page["has_more"] is False


def test_local_playlist_crud_and_entry_pagination(client, session: Session):
    tracks = [_track(index) for index in range(5)]
    session.add_all(tracks)
    session.commit()

    created = client.post("/api/play/playlists", json={"name": "Local crate"})
    assert created.status_code == 200
    playlist_id = created.json()["id"]
    assert created.json()["source"] == "plumdeck"
    assert created.json()["editable"] is True

    entry_ids = []
    for track in tracks:
        result = client.post(f"/api/play/playlists/{playlist_id}/tracks", json={"track_id": track.id})
        assert result.status_code == 200
        entry_ids.append(result.json()["setlist_track_id"])
    page = client.get(f"/api/play/playlists/{playlist_id}/tracks", params={"limit": 2, "offset": 2}).json()
    assert page["total"] == 5
    assert [item["title"] for item in page["items"]] == ["Track 002", "Track 003"]
    assert all("setlist_track_id" in item for item in page["items"])

    renamed = client.patch(f"/api/play/playlists/{playlist_id}", json={"name": "Renamed"})
    assert renamed.json()["name"] == "Renamed"
    assert client.delete(f"/api/play/playlists/{playlist_id}/tracks/{entry_ids[2]}").status_code == 200
    page = client.get(f"/api/play/playlists/{playlist_id}/tracks", params={"limit": 10}).json()
    assert page["total"] == 4
    assert [item["position"] for item in page["items"]] == [0, 1, 2, 3]
    listing = client.get("/api/play/playlists").json()
    assert listing["items"][0]["track_count"] == 4
    assert client.delete(f"/api/play/playlists/{playlist_id}").status_code == 200


def test_mirror_pages_and_copy_skip_unresolved(client, session: Session):
    track = _track(1)
    session.add(track)
    session.commit()
    payload = {
        "source_id": "rb", "source_name": "Rekordbox",
        "playlists": [
            {"external_id": "folder", "name": "Folder", "kind": "folder"},
            {"external_id": "one", "parent_external_id": "folder", "name": "One", "order": 1},
            {"external_id": "two", "parent_external_id": "folder", "name": "Two", "order": 2},
        ],
        "members": [
            {"playlist_external_id": "one", "position": 1, "local_track_id": track.id},
            {"playlist_external_id": "one", "position": 2, "title": "Unavailable"},
        ],
    }
    assert client.post("/api/play/rekordbox/import", json=payload).status_code == 200
    tree = client.get("/api/play/rekordbox/rb/tree/page", params={
        "parent_external_id": "folder", "limit": 1, "offset": 1,
    }).json()
    assert tree["total"] == 2
    assert tree["items"][0]["name"] == "Two"
    assert tree["items"][0]["editable"] is False
    entries = client.get("/api/play/rekordbox/rb/playlists/one/tracks/page", params={"limit": 1}).json()
    assert entries["total"] == 2
    assert len(entries["items"]) == 1
    session.exec(text("UPDATE rekordbox_playlist_tracks SET local_track_id=999999 WHERE source_id='rb' AND position=2"))
    session.commit()
    unresolved = client.get("/api/play/rekordbox/rb/playlists/one/tracks/page", params={"limit": 1, "offset": 1}).json()
    assert unresolved["total"] == 2
    assert unresolved["items"][0]["resolved"] is False

    copied = client.post("/api/play/rekordbox/rb/playlists/one/copy", json={}).json()
    assert copied["copied"] == 1
    assert copied["skipped_unresolved"] == 1
    assert copied["playlist"]["source"] == "plumdeck"
    local_page = client.get(f"/api/play/playlists/{copied['playlist']['id']}/tracks").json()
    assert local_page["total"] == 1


def test_recommendation_page_orders_complete_candidate_set_before_slicing(client, session: Session):
    target = _track(0, bpm=120, key="8A")
    poor = _track(1, bpm=90, key="1A")
    best = _track(2, bpm=120, key="8A")
    middle = _track(3, bpm=122, key="8A")
    zero_bpm = _track(4, bpm=0, key="8A")
    null_bpm = _track(5, bpm=0, key="8A")
    session.add_all([target, poor, best, middle, zero_bpm, null_bpm])
    session.commit()
    session.exec(text("UPDATE tracks SET bpm=NULL WHERE id=:id"), params={"id": null_bpm.id})
    session.commit()
    vector = json.dumps([0.1] * 200)
    for track in (target, poor, best, middle, zero_bpm, null_bpm):
        session.add(TrackEmbedding(track_id=track.id, embedding_json=vector))
    session.commit()

    first = client.get("/api/recommendations/next/page", params={
        "track_id": target.id, "limit": 1, "offset": 0,
    })
    assert first.status_code == 200, first.text
    assert first.json()["total"] == 5
    assert first.json()["items"][0]["id"] == best.id
    second = client.get("/api/recommendations/next/page", params={
        "track_id": target.id, "limit": 1, "offset": 1,
    }).json()
    assert second["items"][0]["id"] == middle.id
    all_items = client.get("/api/recommendations/next/page", params={
        "track_id": target.id, "limit": 10,
    }).json()["items"]
    assert {item["id"] for item in all_items} == {
        poor.id, best.id, middle.id, zero_bpm.id, null_bpm.id,
    }


def test_paged_recommendation_matches_existing_scorer_for_keys_vectors_and_models(session: Session):
    target = _track(10, bpm=120, key="C Major")
    exact = _track(11, bpm=120, key="c major")
    malformed = _track(12, bpm=120, key="C Major")
    adjacent_other_model = _track(13, bpm=120, key="G Major")
    invalid_key = _track(14, bpm=120, key="not-a-key")
    zero_vector = _track(15, bpm=120, key="Cminor")
    null_vector = _track(16, bpm=120, key="A  min")
    uppercase_major = _track(17, bpm=120, key="CM")
    session.add_all([target, exact, malformed, adjacent_other_model, invalid_key, zero_vector, null_vector, uppercase_major])
    session.commit()
    vector = json.dumps([0.1] * 200)
    session.add(TrackEmbedding(track_id=target.id, model_name="musicnn", embedding_json=vector))
    session.add(TrackEmbedding(track_id=exact.id, model_name="musicnn", embedding_json=vector))
    session.add(TrackEmbedding(track_id=malformed.id, model_name="musicnn", embedding_json="bad"))
    session.add(TrackEmbedding(track_id=adjacent_other_model.id, model_name="other", embedding_json=vector))
    session.add(TrackEmbedding(track_id=invalid_key.id, model_name="other", embedding_json=vector))
    session.add(TrackEmbedding(track_id=zero_vector.id, model_name="musicnn", embedding_json=json.dumps([0.0] * 200)))
    session.add(TrackEmbedding(track_id=null_vector.id, model_name="musicnn", embedding_json=json.dumps([None] + [0.1] * 199)))
    session.add(TrackEmbedding(track_id=uppercase_major.id, model_name="other", embedding_json=vector))
    session.commit()

    service = SetlistAppService(session)
    existing = service.recommend_next_track(target.id, limit=20)
    paged = service.recommend_next_track_page(target.id, limit=20)
    assert [track["id"] for track in paged["items"]] == [track["id"] for track in existing]
    target_embedding = session.get(TrackEmbedding, target.id)
    target_vector = service.recommendation_repository._parse_embedding(target_embedding.embedding_json)
    for item in paged["items"]:
        candidate = session.get(Track, item["id"])
        embedding = session.get(TrackEmbedding, item["id"])
        candidate_vector = service.recommendation_repository._parse_embedding(
            embedding.embedding_json if embedding else None
        )
        expected = calculate_mixability_score(
            target.bpm, target.key, candidate.bpm, candidate.key,
            cosine_similarity(
                target_vector, candidate_vector, target_embedding.model_name,
                embedding.model_name if embedding else None,
            ),
        )
        assert item["recommendation_score"] == pytest.approx(expected)


def test_recommendation_feature_tiebreak_is_applied_before_deep_paging(session: Session):
    target = _track(1000, bpm=120, key="8A")
    session.add(target)
    session.commit()
    session.exec(text("""
        INSERT INTO tracks
        (filepath,title,artist,album,genre,subgenre,bpm,key,scale,duration,energy,
         danceability,loudness,brightness,noisiness,contrast,loudness_range,
         spectral_flux,spectral_rolloff,is_genre_verified,created_at)
        SELECT '/rec-bulk/' || i || '.mp3', 'Candidate ' || i, 'Artist', 'Album',
               'House','',120,'8A','',180,0,
               CASE WHEN i=249 THEN 0.9 ELSE 0.1 END,
               -60,0,0,0,0,0,0,false,CURRENT_TIMESTAMP
        FROM range(250) AS candidates(i)
    """))
    session.commit()
    service = SetlistAppService(session)
    existing = service.recommend_next_track(
        target.id, limit=1, target_params={"danceability": 0.9},
    )
    page = service.recommend_next_track_page(
        target.id, limit=1, target_params={"danceability": 0.9},
    )
    assert page["total"] == 250
    assert page["items"][0]["id"] == existing[0]["id"]
    assert page["items"][0]["title"] == "Candidate 249"


def test_collection_page_sorts_across_the_whole_library(client, session: Session):
    # 並べ替えは読み込み済みのページではなくライブラリ全体に効く必要がある。
    for index, (title, artist, bpm, key, duration) in enumerate([
        ("Charlie", "Zeta", 128.0, "A minor", 200.0),
        ("alpha", "Yankee", 90.0, "C major", 100.0),
        ("Bravo", "xray", 174.0, "", 300.0),
    ]):
        track = _track(index, bpm=bpm, key=key)
        track.title, track.artist, track.duration = title, artist, duration
        session.add(track)
    session.commit()

    def page(**params):
        response = client.get("/api/tracks/page", params={"limit": 2, **params})
        assert response.status_code == 200
        return response.json()

    ascending = page(sort="bpm", order="asc", limit=3)["items"]
    assert [row["bpm"] for row in ascending] == [90.0, 128.0, 174.0]
    assert [row["bpm"] for row in page(sort="bpm", order="desc", limit=3)["items"]] == [174.0, 128.0, 90.0]
    # 先頭ページの続きも同じ並びのまま返る（ページ境界がぶれない）。
    assert [row["bpm"] for row in page(sort="bpm", order="asc")["items"]] == [90.0, 128.0]
    assert [row["bpm"] for row in page(sort="bpm", order="asc", offset=2)["items"]] == [174.0]
    # 大文字小文字を無視した文字列順。
    assert [row["title"] for row in page(sort="title", limit=3)["items"]] == ["alpha", "Bravo", "Charlie"]
    assert [row["artist"] for row in page(sort="artist", limit=3)["items"]] == ["xray", "Yankee", "Zeta"]
    assert [row["duration"] for row in page(sort="duration", order="desc", limit=3)["items"]] == [300.0, 200.0, 100.0]
    # キーは Camelot 順（8B=C major の次に 8A=A minor）。未設定は末尾。
    assert [row["key"] for row in page(sort="key", limit=3)["items"]] == ["A minor", "C major", ""]
    # 表記ゆれ（大文字の Minor、Camelot 表記そのもの）も同じ順位に落ちる。
    session.add(_track(90, key="F Minor"))   # 7A
    session.add(_track(91, key="8A"))        # A minor と同じ 8A
    session.commit()
    assert [row["key"] for row in page(sort="key", limit=5)["items"]] == ["F Minor", "A minor", "8A", "C major", ""]

    # 未知の列は既定の並びのまま、不正な向きは弾く。
    default_order = [row["id"] for row in page(limit=3)["items"]]
    assert [row["id"] for row in page(sort="nonexistent", limit=3)["items"]] == default_order
    assert client.get("/api/tracks/page", params={"sort": "bpm", "order": "sideways"}).status_code == 422
