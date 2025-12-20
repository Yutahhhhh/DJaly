from sqlmodel import Session
from models import Track

def test_get_tracks_filtering(client, session: Session):
    """楽曲一覧のフィルタリング機能のE2Eテスト"""
    # 1. セットアップ
    tracks = [
        Track(filepath="/path/1.mp3", title="A-Track", artist="Art1", album="Album1", genre="House", bpm=120, duration=100),
        Track(filepath="/path/2.mp3", title="B-Track", artist="Art2", album="Album2", genre="Techno", bpm=130, duration=100),
        Track(filepath="/path/3.mp3", title="C-Track", artist="Art1", album="Album1", genre="House", bpm=122, duration=100),
    ]
    for t in tracks: session.add(t)
    session.commit()

    # 2. ジャンルフィルタ
    response = client.get("/api/tracks", params={"genres": ["House"]})
    assert len(response.json()) == 2
    
    # 3. アーティスト検索 (Partial match)
    response = client.get("/api/tracks", params={"artist": "Art2"})
    assert len(response.json()) == 1
    assert response.json()[0]["title"] == "B-Track"

    # 4. BPM範囲検索 (BPM 120 +/- 5)
    response = client.get("/api/tracks", params={"bpm": 120, "bpm_range": 5.0})
    # 120 と 122 がヒットするはず
    assert len(response.json()) == 2

def test_update_track_genre(client, session: Session):
    """ジャンル更新APIのテスト"""
    track = Track(filepath="/p/1.mp3", title="T", artist="A", album="AlbumT", genre="Old", bpm=120, duration=100)
    session.add(track)
    session.commit()
    session.refresh(track)

    response = client.patch(
        f"/api/tracks/{track.id}/genre",
        json={"genre": "New Genre"}
    )
    assert response.status_code == 200
    assert response.json()["genre"] == "New Genre"
    assert response.json()["is_genre_verified"] is True

    # DB側も更新されているか確認
    session.refresh(track)
    assert track.genre == "New Genre"

def test_vibe_search_integration(client, session: Session, mocker):
    """LLMプロンプトを用いたVibe検索の統合テスト"""
    # 1. データの準備
    t1 = Track(filepath="/v1.mp3", title="Chill", energy=0.2, bpm=90, duration=100, artist="A", album="B", genre="C")
    t2 = Track(filepath="/v2.mp3", title="Energy", energy=0.9, bpm=140, duration=100, artist="A", album="B", genre="C")
    session.add(t1)
    session.add(t2)
    session.commit()

    # 2. LLMのレスポンスをモック (エナジーが高い値を返すように)
    mock_params = mocker.patch("app.services.track_app_service.generate_vibe_parameters")
    mock_params.return_value = {"bpm": 140, "energy": 0.9, "danceability": 0.8, "brightness": 0.8, "noisiness": 0.1}

    # 3. リクエスト実行
    response = client.get("/api/tracks", params={"vibe_prompt": "Fast and energetic peak time track"})
    data = response.json()

    # 4. 期待値: Energyが高い t2 が先頭に来る
    assert data[0]["title"] == "Energy"

def test_suggest_genre(client, session: Session, mocker):
    t1 = Track(filepath="/s1.mp3", title="S1", artist="A", album="B", genre="Unknown", bpm=120, duration=100)
    session.add(t1)
    session.commit()
    
    # RecommendationAppService.suggest_genre をモック
    # 実際にはLLMやルールベースで提案するが、ここではモック
    mock_suggest = mocker.patch("app.services.recommendation_app_service.RecommendationAppService.suggest_genre")
    mock_suggest.return_value = {"suggested_genre": "Techno", "reason": "BPM"}
    
    response = client.get(f"/api/tracks/{t1.id}/suggest-genre")
    assert response.status_code == 200
    assert response.json()["suggested_genre"] == "Techno"

def test_get_similar_tracks(client, session: Session):
    t1 = Track(filepath="/sim1.mp3", title="Sim1", artist="A", album="B", genre="G", bpm=120, duration=100)
    t2 = Track(filepath="/sim2.mp3", title="Sim2", artist="A", album="B", genre="G", bpm=120, duration=100)
    session.add(t1)
    session.add(t2)
    session.commit()
    
    from models import TrackEmbedding
    import json
    vec = [0.1] * 200
    te1 = TrackEmbedding(track_id=t1.id, embedding_json=json.dumps(vec))
    te2 = TrackEmbedding(track_id=t2.id, embedding_json=json.dumps(vec))
    session.add(te1)
    session.add(te2)
    session.commit()
    
    response = client.get(f"/api/tracks/{t1.id}/similar")
    assert response.status_code == 200
    data = response.json()
    assert len(data) > 0
    assert data[0]["title"] == "Sim2"

