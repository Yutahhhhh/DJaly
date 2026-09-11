import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from sqlalchemy import text
from sqlmodel import Session

import infra.database.connection as db
from infra.database.schema import init_raw_db
from domain.models.track import Track, TrackAnalysis, TrackEmbedding
from domain.services.analysis.portable import PortableAudioAnalyzer
from utils.ingestion import (
    has_completed_analysis,
    has_completed_analysis_for_profile,
    has_completed_analysis_result,
)


def test_portable_light_analysis_uses_a_bounded_middle_window(monkeypatch):
    analyzer = object.__new__(PortableAudioAnalyzer)
    requested = {}
    analyzer._extract_metadata = lambda _: SimpleNamespace(
        duration=300, title="Title", artist="DJ", album="Album",
        genre="House", year="2026", extra={},
    )

    def load(_path, start, duration):
        requested.update(start=start, duration=duration)
        return np.full(44100, .1, dtype=np.float32)

    analyzer._load_audio_segment = load
    analyzer._rhythm = lambda _audio: (126.0, np.array([.1, .58]), .8, np.array([]), np.array([.48]))
    analyzer._key = lambda _audio: ("C", "minor", .7)
    analyzer._extract_light_features = lambda _audio: {
        "energy": .25, "brightness": .4, "noisiness": .1,
        "loudness": -12.0, "loudness_range": 4.0,
        "spectral_flux": .2, "spectral_rolloff": 4000.0, "contrast": .3,
    }
    analyzer._extract_embedding = lambda _audio: (_ for _ in ()).throw(
        AssertionError("light analysis must not load MusiCNN")
    )

    result = analyzer.analyze_light("/music/track.mp3")

    assert requested == {"start": 105.0, "duration": 90}
    assert result["analysis_level"] == "light"
    assert result["bpm"] == 126.0
    assert result["duration"] == 300
    assert "embedding" not in result
    assert result["features_extra"]["playback_grid_estimated"] is True


def test_light_result_is_complete_without_faking_an_embedding():
    result = {
        "title": "Title", "artist": "DJ", "duration": 60,
        "bpm": 126, "analysis_level": "light",
    }
    assert has_completed_analysis_result(result)
    track = SimpleNamespace(
        title="Title", artist="DJ", duration=60, bpm=126,
        analysis_level="light",
    )
    assert has_completed_analysis(track, None)
    assert not has_completed_analysis_for_profile(track, None, "full")
    assert not has_completed_analysis_for_profile(track, [.1] * 200, "full")

    failed = SimpleNamespace(
        title="Title", artist="DJ", duration=60, bpm=126,
        analysis_level=None,
    )
    assert not has_completed_analysis(failed, None)


def test_light_save_does_not_downgrade_an_existing_full_analysis(tmp_path):
    from infra.repositories.ingestion_repository import IngestionRepository

    engine = db.create_library_engine(f"duckdb:///{tmp_path / 'library.duckdb'}")
    init_raw_db(engine)
    try:
        with Session(engine) as session:
            track = Track(
                filepath=str(tmp_path / "track.mp3"), title="Title", artist="DJ",
                genre="House", duration=180, bpm=126, analysis_level="full",
                energy=.8, danceability=.7,
            )
            session.add(track)
            session.flush()
            session.add(TrackEmbedding(
                track_id=track.id, embedding_json=json.dumps([.1] * 200),
                model_name="musicnn",
            ))
            session.add(TrackAnalysis(
                track_id=track.id,
                features_extra_json=json.dumps({"analysis_level": "full", "waveform_peaks": [1]}),
            ))
            session.commit()

            IngestionRepository().save_track_result(session, {
                "filepath": track.filepath, "title": "Title", "artist": "DJ",
                "genre": "House", "duration": 180, "bpm": 124,
                "analysis_level": "light", "energy": .2, "danceability": .1,
                "features_extra": {"analysis_level": "light"},
            })
            saved = session.get(Track, track.id)
            analysis = session.get(TrackAnalysis, track.id)
            assert saved.analysis_level == "full"
            assert saved.bpm == 126
            assert saved.energy == pytest.approx(.8)
            assert json.loads(analysis.features_extra_json)["analysis_level"] == "full"
    finally:
        engine.dispose()


def test_analyze_track_file_keeps_full_path_when_light_is_not_supported(monkeypatch):
    import ingest

    called = []
    analyzer = SimpleNamespace(
        analyze=lambda filepath, **kwargs: called.append((filepath, kwargs)) or {"ok": True}
    )
    monkeypatch.setattr(ingest, "get_analyzer", lambda: analyzer)

    assert ingest.analyze_track_file("track.mp3", analysis_profile="light") == {"ok": True}
    assert called == [("track.mp3", {
        "skip_basic": False, "skip_waveform": False, "external_lyrics": None,
    })]


def test_explicit_full_play_import_upgrades_a_light_track(tmp_path, monkeypatch):
    from app.services import play_import_service as play_module
    from domain.services import ingestion_domain_service as ingestion_module

    engine = db.create_library_engine(f"duckdb:///{tmp_path / 'upgrade.duckdb'}")
    monkeypatch.setattr(db, "engine", engine)
    init_raw_db(engine)
    path = tmp_path / "light.mp3"
    path.write_bytes(b"audio")
    calls = []

    class ImmediateExecutor:
        def __init__(self, *_, task_timeout=None, **__):
            self.task_timeout = task_timeout
        def __enter__(self):
            return self
        def __exit__(self, *_):
            return False

    class FullDomain:
        async def process_track_ingestion(self, filepath, _force, _loop, **kwargs):
            calls.append(kwargs["analysis_profile"])
            return {
                "filepath": filepath, "title": "Title", "artist": "DJ",
                "genre": "House", "duration": 60, "bpm": 126,
                "analysis_level": "full", "features_extra": {"analysis_level": "full"},
                "embedding": [.1] * 200, "embedding_model": "musicnn",
            }

    monkeypatch.setattr(play_module, "AnalysisExecutor", ImmediateExecutor)
    monkeypatch.setattr(ingestion_module, "IngestionDomainService", FullDomain)
    try:
        with Session(engine) as session:
            light = Track(
                filepath=str(path), title="Title", artist="DJ", genre="House",
                duration=60, bpm=126, analysis_level="light",
            )
            session.add(light)
            session.commit()
            batch = play_module.PlayImportService(session).create(
                "upgrade-light", "collection", None, [str(path)],
                analysis_profile="full",
            )
            session.rollback()
        play_module.process_batch(batch["id"])
        with Session(engine) as session:
            saved_batch = play_module.PlayImportService(session).get(batch["id"])
            upgraded = session.exec(text("SELECT analysis_level FROM tracks")).one()[0]
            assert saved_batch["items"][0]["state"] == "completed"
            assert saved_batch["items"][0]["analysis_level"] == "full"
            assert upgraded == "full"
            assert session.exec(text("SELECT count(*) FROM track_embeddings")).one()[0] == 1
        assert calls == ["full"]
    finally:
        engine.dispose()


def test_windows_auto_play_import_reuses_an_existing_light_track(tmp_path, monkeypatch):
    from app.services import play_import_service as play_module

    engine = db.create_library_engine(f"duckdb:///{tmp_path / 'reuse-light.duckdb'}")
    monkeypatch.setattr(db, "engine", engine)
    init_raw_db(engine)
    path = tmp_path / "light.mp3"
    path.write_bytes(b"audio")

    class ImmediateExecutor:
        def __init__(self, *_, task_timeout=None, **__):
            self.task_timeout = task_timeout
        def __enter__(self):
            return self
        def __exit__(self, *_):
            return False

    monkeypatch.setattr(play_module.sys, "platform", "win32")
    monkeypatch.setattr(play_module, "AnalysisExecutor", ImmediateExecutor)
    try:
        with Session(engine) as session:
            session.add(Track(
                filepath=str(path), title="Title", artist="DJ", genre="House",
                duration=60, bpm=126, analysis_level="light",
            ))
            session.commit()
            batch = play_module.PlayImportService(session).create(
                "reuse-auto-light", "collection", None, [str(path)],
                analysis_profile="auto",
            )
            session.rollback()

        play_module.process_batch(batch["id"])

        with Session(engine) as session:
            saved = play_module.PlayImportService(session).get(batch["id"])
            assert saved["state"] == "completed"
            assert saved["items"][0]["state"] == "existing"
            assert saved["items"][0]["analysis_level"] == "light"
            assert session.exec(text("SELECT count(*) FROM track_embeddings")).one()[0] == 0
    finally:
        engine.dispose()


def test_windows_auto_play_import_falls_back_once_and_persists_light(tmp_path, monkeypatch):
    from app.services import play_import_service as play_module
    from domain.services import ingestion_domain_service as ingestion_module

    engine = db.create_library_engine(f"duckdb:///{tmp_path / 'queue.duckdb'}")
    monkeypatch.setattr(db, "engine", engine)
    init_raw_db(engine)
    first = tmp_path / "first.mp3"
    second = tmp_path / "second.mp3"
    first.write_bytes(b"first")
    second.write_bytes(b"second")
    calls = []

    class ImmediateExecutor:
        def __init__(self, *_, task_timeout=None, **__):
            self.task_timeout = task_timeout
        def __enter__(self):
            return self
        def __exit__(self, *_):
            return False

    class FakeDomain:
        async def process_track_ingestion(self, filepath, _force, _loop, **kwargs):
            profile = kwargs["analysis_profile"]
            calls.append((Path(filepath).name, profile))
            if profile == "full":
                raise RuntimeError("wrapped") from TimeoutError("Analysis timed out after 180 seconds")
            return {
                "filepath": filepath, "title": Path(filepath).stem,
                "artist": "DJ", "genre": "House", "duration": 60,
                "bpm": 126, "key": "C minor", "scale": "minor",
                "analysis_level": "light",
                "features_extra": {"analysis_level": "light"},
            }

    monkeypatch.setattr(play_module.sys, "platform", "win32")
    monkeypatch.setattr(play_module, "AnalysisExecutor", ImmediateExecutor)
    monkeypatch.setattr(ingestion_module, "IngestionDomainService", FakeDomain)
    try:
        with Session(engine) as session:
            batch = play_module.PlayImportService(session).create(
                "auto-light", "collection", None, [str(first), str(second)],
                analysis_profile="auto",
            )
            session.rollback()
        play_module.process_batch(batch["id"])
        with Session(engine) as session:
            saved = play_module.PlayImportService(session).get(batch["id"])
            assert saved["state"] == "completed"
            assert saved["effective_analysis_profile"] == "light"
            assert [item["analysis_level"] for item in saved["items"]] == ["light", "light"]
            assert session.exec(text("SELECT count(*) FROM track_embeddings")).one()[0] == 0
        assert calls == [("first.mp3", "full"), ("first.mp3", "light"), ("second.mp3", "light")]
    finally:
        engine.dispose()


def test_windows_auto_explorer_falls_back_and_uses_light_for_remaining_files(
    tmp_path, monkeypatch,
):
    from app.services import ingestion_app_service as app_module

    first = tmp_path / "first.mp3"
    second = tmp_path / "second.mp3"
    first.touch()
    second.touch()
    calls = []

    class ImmediateExecutor:
        def __init__(self, *_, task_timeout=None, **__):
            self.task_timeout = task_timeout
        def shutdown(self, *_, **__):
            return None

    class FakeDomain:
        async def process_track_ingestion(self, filepath, _force, _loop, *_args, **kwargs):
            profile = kwargs["analysis_profile"]
            calls.append((Path(filepath).name, profile))
            if profile == "full":
                raise RuntimeError("wrapped") from TimeoutError("Analysis timed out")
            return {"analysis_level": "light"}

    monkeypatch.setattr(app_module.sys, "platform", "win32")
    monkeypatch.setattr(app_module, "AnalysisExecutor", ImmediateExecutor)
    monkeypatch.setattr(app_module, "expand_targets", lambda targets: targets)
    monkeypatch.setattr(
        app_module, "filter_and_prioritize_files",
        lambda targets, _force, _profile: (targets, 0),
    )
    service = app_module.IngestionAppService()
    service.domain_service = FakeDomain()

    asyncio.run(service._run_ingestion([str(first), str(second)], False, "auto"))

    assert calls == [("first.mp3", "full"), ("first.mp3", "light"), ("second.mp3", "light")]
    assert service.state["type"] == "complete"
    assert service.state["processed"] == 2
    assert service.state["details"]["effective_analysis_profile"] == "light"
