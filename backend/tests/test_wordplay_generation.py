"""Approved directional relationships influence selection, not eligibility."""
import json

from domain.models.track import Track
from domain.models.wordplay import WordplayPair
from app.services.setlist_app_service import SetlistAppService


def seed_tracks(session):
    tracks = []
    for n in range(4):
        t = Track(filepath=f'/wordplay-generation/{n}.mp3', title=f'Track {n}',
                  artist=f'Artist {n}', genre='House', bpm=120, duration=180,
                  key='8A', energy=0.5, year=2020)
        session.add(t)
        tracks.append(t)
    session.commit()
    return tracks


def add_pair(session, a, b, status='pending'):
    p = WordplayPair(from_track_id=a.id, to_track_id=b.id, keyword='yeah',
                     normalized_keyword='yeah', source_phrase='yeah', target_phrase='yeah', status=status)
    session.add(p)
    session.commit()
    return p


def test_pending_never_generates_metadata_and_approved_direction_is_used(session):
    a, b, c, d = seed_tracks(session)
    pair = add_pair(session, a, c)
    service = SetlistAppService(session)
    pending = service.generate_auto_setlist(limit=2, seed_track_ids=[a.id])
    assert pending[1]['id'] == b.id
    assert all('wordplay_json' not in item for item in pending)

    pair.status = 'approved'
    session.add(pair)
    session.commit()
    approved = service.generate_auto_setlist(limit=2, seed_track_ids=[a.id])
    assert [t['id'] for t in approved] == [a.id, c.id]
    wp = json.loads(approved[1]['wordplay_json'])
    assert wp['from_track_id'] == a.id and wp['pair_id'] == pair.id
    assert wp['verification_status'] == 'unverified'
    reverse = service.generate_auto_setlist(limit=2, seed_track_ids=[c.id])
    assert all('wordplay_json' not in t for t in reverse)


def test_approved_next_and_path_metadata_and_delete_stops_reuse(session):
    a, b, c, d = seed_tracks(session)
    pair = add_pair(session, a, c, 'approved')
    service = SetlistAppService(session)
    nxt = service.recommend_next_track(a.id)
    assert nxt[0]['id'] == c.id
    assert json.loads(nxt[0]['wordplay_json'])['pair_id'] == pair.id
    path = service.generate_path_setlist(a.id, d.id, 3)
    assert [t['id'] for t in path] == [a.id, c.id, d.id]
    assert json.loads(path[1]['wordplay_json'])['from_track_id'] == a.id

    saved = service.create_setlist('Approved transitions')
    service.update_setlist_tracks(saved.id, path)
    session.delete(pair)
    session.commit()
    assert all('wordplay_json' not in t for t in service.recommend_next_track(a.id))
    # Deleting the registry item does not erase an already-used setlist annotation.
    stored = service.get_setlist_tracks(saved.id)
    assert json.loads(stored[1]['wordplay_json'])['keyword'] == 'yeah'


def test_approval_cannot_override_genre_year_or_tempo_filters(session):
    a, b, c, d = seed_tracks(session)
    c.genre = 'Hip-Hop'
    d.year = 1990
    session.add(c); session.add(d); session.commit()
    add_pair(session, a, c, 'approved')
    add_pair(session, a, d, 'approved')
    service = SetlistAppService(session)
    result = service.generate_auto_setlist(
        limit=3, seed_track_ids=[a.id], genres=['House'], target_params={'year_min': 2010}
    )
    assert [t['id'] for t in result] == [a.id, b.id]
    assert all('wordplay_json' not in t for t in result)

    c.genre = 'House'; c.bpm = 500
    session.add(c); session.commit()
    nxt = service.recommend_next_track(a.id, genres=['House'], target_params={'year_min': 2010})
    assert [t['id'] for t in nxt] == [b.id]


def test_approved_destination_survives_normal_pool_limit(session, monkeypatch):
    a, b, c, d = seed_tracks(session)
    add_pair(session, a, c, 'approved')
    service = SetlistAppService(session)
    original = service.recommendation_repository.fetch_candidates_pool

    def capped(*args, **kwargs):
        if kwargs.get('candidate_ids') is None:
            kwargs['limit'] = 1
        return original(*args, **kwargs)

    monkeypatch.setattr(service.recommendation_repository, 'fetch_candidates_pool', capped)
    result = service.recommend_next_track(a.id)
    assert result[0]['id'] == c.id
    assert json.loads(result[0]['wordplay_json'])['from_track_id'] == a.id


def test_unrelated_approved_pair_cannot_expand_a_different_chain(session, monkeypatch):
    a, b, x, y = seed_tracks(session)
    service = SetlistAppService(session)
    original = service.recommendation_repository.fetch_candidates_pool

    def capped(*args, **kwargs):
        if kwargs.get('candidate_ids') is None:
            kwargs['limit'] = 1
        return original(*args, **kwargs)

    monkeypatch.setattr(service.recommendation_repository, 'fetch_candidates_pool', capped)
    before = service.generate_auto_setlist(limit=3, seed_track_ids=[a.id], target_params={'bpm': 120})
    assert [t['id'] for t in before] == [a.id, b.id]
    add_pair(session, x, y, 'approved')
    after = service.generate_auto_setlist(limit=3, seed_track_ids=[a.id], target_params={'bpm': 120})
    assert [t['id'] for t in after] == [a.id, b.id]
    path = service.generate_path_setlist(a.id, x.id, 4)
    assert [t['id'] for t in path] == [a.id, b.id, x.id]
