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

    # 5. Subgenre Filter (using genres param)
    t4 = Track(filepath="/path/4.mp3", title="D-Track", artist="Art3", album="Album3", genre="House", subgenre="Deep House", bpm=120, duration=100)
    session.add(t4)
    session.commit()
    
    response = client.get("/api/tracks", params={"genres": ["Deep House"]})
    assert len(response.json()) == 1
    assert response.json()[0]["title"] == "D-Track"

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

def test_genre_expansion_search(client, session: Session, mocker):
    """ジャンル展開検索（親ジャンル検索）のテスト"""
    # 1. データ準備
    # Parent Genre Track
    t1 = Track(filepath="/p.mp3", title="Parent Track", artist="A", album="B", genre="House", bpm=120, duration=100)
    # Child Genre Track
    t2 = Track(filepath="/c.mp3", title="Child Track", artist="A", album="B", genre="Deep House", bpm=120, duration=100)
    # Unrelated Track
    t3 = Track(filepath="/o.mp3", title="Other Track", artist="A", album="B", genre="Techno", bpm=120, duration=100)
    
    session.add(t1)
    session.add(t2)
    session.add(t3)
    session.commit()

    # 2. GenreExpanderのモック
    # expand("House") -> ["House", "Deep House"] を返すように設定
    mock_expand = mocker.patch("utils.genres.genre_expander.expand")
    mock_expand.return_value = ["House", "Deep House"]

    # 3. 親ジャンル検索 (expand:House)
    # House(親)とDeep House(子)の両方がヒットするはず
    response = client.get("/api/tracks", params={"genres": ["expand:House"]})
    assert response.status_code == 200
    data = response.json()
    titles = [t["title"] for t in data]
    assert "Parent Track" in titles
    assert "Child Track" in titles
    assert "Other Track" not in titles
    
    # モックが正しい引数で呼ばれたか確認
    # 注意: 実装では "expand:" プレフィックスを除去して "House" を渡しているはず
    mock_expand.assert_called_with(mocker.ANY, "House")

    # 4. 通常検索 (House)
    # House(親)のみヒットし、Deep House(子)はヒットしないはず
    # ※ 実装上、通常検索では genre_expander.expand は呼ばれない、または呼ばれても展開ロジックを通らない
    response_normal = client.get("/api/tracks", params={"genres": ["House"]})
    assert response_normal.status_code == 200
    data_normal = response_normal.json()
    titles_normal = [t["title"] for t in data_normal]
    
    assert "Parent Track" in titles_normal
    assert "Child Track" not in titles_normal



def test_get_tracks_year_filtering(client, session: Session):
    """リリース年によるフィルタリング機能のテスト"""
    # 1. セットアップ
    tracks = [
        Track(filepath="/y1.mp3", title="90s Track", artist="A", album="B", genre="G", bpm=120, duration=100, year=1995),
        Track(filepath="/y2.mp3", title="2000s Track", artist="A", album="B", genre="G", bpm=120, duration=100, year=2005),
        Track(filepath="/y3.mp3", title="Recent Track", artist="A", album="B", genre="G", bpm=120, duration=100, year=2023),
        Track(filepath="/y4.mp3", title="No Year Track", artist="A", album="B", genre="G", bpm=120, duration=100, year=None),
    ]
    for t in tracks: session.add(t)
    session.commit()

    # 2. 範囲指定 (2000 - 2010) -> 2005年の曲のみヒット
    response = client.get("/api/tracks", params={"min_year": 2000, "max_year": 2010})
    data = response.json()
    assert len(data) == 1
    assert data[0]["title"] == "2000s Track"

    # 3. 最小年指定 (2020以降) -> 2023年の曲のみヒット
    response = client.get("/api/tracks", params={"min_year": 2020})
    data = response.json()
    assert len(data) == 1
    assert data[0]["title"] == "Recent Track"

    # 4. 最大年指定 (1999以前) -> 1995年の曲のみヒット
    response = client.get("/api/tracks", params={"max_year": 1999})
    data = response.json()
    assert len(data) == 1
    assert data[0]["title"] == "90s Track"

def test_get_tracks_includes_year(client, session: Session):
    """APIレスポンスにyearが含まれているか確認"""
    track = Track(
        filepath="/path/year.mp3", 
        title="Year Track", 
        artist="Artist", 
        album="Album", 
        genre="Pop", 
        year=1999, 
        bpm=120, 
        duration=100
    )
    session.add(track)
    session.commit()

    response = client.get("/api/tracks")
    data = response.json()
    
    assert len(data) == 1
    assert data[0]["year"] == 1999
