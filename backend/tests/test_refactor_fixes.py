"""
refactor/ ドキュメント (BUG-01, BUG-02, BUG-03, BUG-04, BUG-10, AI-07) の改修に対するテスト
"""
import json
import pytest
from sqlmodel import Session

from models import Track
from domain.models.track import TrackEmbedding
from utils.llm import sanitize_vibe_params, clear_vibe_cache


# --- BUG-04: vibe パラメータの検証 ---

class TestSanitizeVibeParams:
    def test_valid_params_passthrough(self):
        params = sanitize_vibe_params({"bpm": 128, "energy": 0.8, "year_min": 1990, "year_max": 1999})
        assert params["bpm"] == 128
        assert params["energy"] == 0.8
        assert params["year_min"] == 1990
        assert params["year_max"] == 1999

    def test_string_numbers_are_coerced(self):
        params = sanitize_vibe_params({"bpm": "120", "energy": "0.9"})
        assert params["bpm"] == 120.0
        assert params["energy"] == 0.9

    def test_invalid_values_are_dropped(self):
        params = sanitize_vibe_params({"bpm": "fast", "energy": None, "danceability": 0.5})
        assert "bpm" not in params
        assert "energy" not in params
        assert params["danceability"] == 0.5

    def test_scale_normalization(self):
        # 1-10 / 0-100 スケールの正規化
        assert sanitize_vibe_params({"energy": 8})["energy"] == 0.8
        assert sanitize_vibe_params({"energy": 85})["energy"] == 0.85

    def test_clamping(self):
        params = sanitize_vibe_params({"bpm": 999, "year_min": 1500})
        assert params["bpm"] == 200.0
        assert "year_min" not in params

    def test_year_swap(self):
        params = sanitize_vibe_params({"year_min": 2010, "year_max": 1990})
        assert params["year_min"] == 1990
        assert params["year_max"] == 2010

    def test_non_dict_input(self):
        assert sanitize_vibe_params(None) == {}
        assert sanitize_vibe_params("not a dict") == {}


# --- AI-07: vibe キャッシュ ---

def test_vibe_params_cached(session: Session, mocker):
    clear_vibe_cache()
    mock_gen = mocker.patch(
        "utils.llm.generate_text",
        return_value='{"bpm": 100, "energy": 0.5}'
    )
    from utils.llm import generate_vibe_parameters

    p1 = generate_vibe_parameters("test vibe prompt", session=session)
    p2 = generate_vibe_parameters("test vibe prompt", session=session)

    assert p1 == p2
    assert p1["bpm"] == 100
    assert mock_gen.call_count == 1  # 2回目はキャッシュ
    clear_vibe_cache()


# --- BUG-02: wordplay の null 削除 ---

def test_wordplay_delete_with_null(client, session: Session):
    # セットリストと楽曲を作成
    res = client.post("/api/setlists", json={"name": "Test Set"})
    assert res.status_code == 200
    setlist_id = res.json()["id"]

    track = Track(filepath="/tmp/wp_test.mp3", title="WP", artist="Tester", bpm=120.0)
    session.add(track)
    session.commit()
    session.refresh(track)

    res = client.post(
        f"/api/setlists/{setlist_id}/tracks",
        json=[{"id": track.id, "wordplay_json": '{"keyword": "test"}'}],
    )
    assert res.status_code == 200

    tracks = client.get(f"/api/setlists/{setlist_id}/tracks").json()
    st_id = tracks[0]["setlist_track_id"]
    assert tracks[0]["wordplay_json"] is not None

    # null での削除が 422 にならず成功すること
    res = client.patch(
        f"/api/setlist-tracks/{st_id}/wordplay",
        json={"wordplay_json": None},
    )
    assert res.status_code == 200

    tracks = client.get(f"/api/setlists/{setlist_id}/tracks").json()
    assert tracks[0]["wordplay_json"] is None


# --- BUG-01: 類似曲サジェストの similarity 値 ---

def test_suggestion_similarity_values(session: Session):
    from app.services.recommendation_app_service import RecommendationAppService

    # 親 (verified) + 候補 (unverified) を作成
    parent = Track(filepath="/tmp/sim_parent.mp3", title="P", artist="A", genre="House", is_genre_verified=True)
    cand_a = Track(filepath="/tmp/sim_a.mp3", title="A", artist="B", is_genre_verified=False)
    cand_b = Track(filepath="/tmp/sim_b.mp3", title="B", artist="C", is_genre_verified=False)
    session.add_all([parent, cand_a, cand_b])
    session.commit()
    for t in (parent, cand_a, cand_b):
        session.refresh(t)

    session.add_all([
        TrackEmbedding(track_id=parent.id, embedding_json="[1.0, 0.0]"),
        TrackEmbedding(track_id=cand_a.id, embedding_json="[1.0, 0.0]"),   # sim = 1.0
        TrackEmbedding(track_id=cand_b.id, embedding_json="[0.6, 0.8]"),   # sim = 0.6
    ])
    session.commit()

    service = RecommendationAppService(session)
    suggestions = service.get_suggestions_for_track(parent.id, threshold=0.5)

    assert len(suggestions) == 2
    # 降順ソートかつ、各 track に正しい similarity が紐づくこと
    assert suggestions[0].id == cand_a.id
    assert suggestions[0].similarity == pytest.approx(1.0)
    assert suggestions[1].id == cand_b.id
    assert suggestions[1].similarity == pytest.approx(0.6)


# --- BUG-03 / BUG-04: fetch_candidates_pool ---

def test_fetch_candidates_pool_robust_params(session: Session):
    from infra.repositories.recommendation_repository import RecommendationRepository

    t1 = Track(filepath="/tmp/pool_1.mp3", title="T1", artist="A", genre="House", subgenre="Deep House", bpm=120.0, energy=0.5)
    t2 = Track(filepath="/tmp/pool_2.mp3", title="T2", artist="B", genre="Techno", subgenre="Hard Techno", bpm=140.0, energy=0.9)
    session.add_all([t1, t2])
    session.commit()

    repo = RecommendationRepository(session)

    # 文字列の bpm/energy でも 500 にならない
    pool = repo.fetch_candidates_pool({"bpm": "120", "energy": "0.5"})
    assert len(pool) >= 1

    # subgenres フィルタが効くこと
    pool = repo.fetch_candidates_pool({}, subgenres=["Deep House"])
    assert len(pool) == 1
    assert pool[0]["track"].subgenre == "Deep House"

    # genres と subgenres の OR 結合
    pool = repo.fetch_candidates_pool({}, genres=["Techno"], subgenres=["Deep House"])
    assert len(pool) == 2


# --- BUG-10: Unknown は verified にしない ---

def test_unknown_genre_not_verified(session: Session, mocker):
    from app.services.genre_app_service import GenreAppService
    from api.schemas.genres import AnalysisMode

    track = Track(filepath="/tmp/unknown_g.mp3", title="U", artist="X", genre=None, is_genre_verified=False)
    session.add(track)
    session.commit()
    session.refresh(track)

    mocker.patch(
        "app.services.genre_app_service.generate_text",
        return_value=f"{track.id}|Unknown"
    )

    service = GenreAppService(session)
    service.analyze_tracks_batch_with_llm([track.id], mode=AnalysisMode.GENRE)

    session.refresh(track)
    assert track.is_genre_verified is False  # 再解析の導線が残る
