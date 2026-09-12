import json
import threading

import pytest
from sqlmodel import Session

from api.schemas.performance_metadata import BeatGrid
from app.services.analysis_job_service import AnalysisJobService
from app.services.grid_candidate_service import GridCandidateService
from app.services.performance_metadata_app_service import PerformanceMetadataAppService
from domain.models.performance_metadata import TrackPerformanceMetadata
from domain.models.track import Track, TrackAnalysis, TrackEmbedding
from domain.services.analysis.beat_grid import VERSION
from domain.services.analysis.constants import GRID_COMPONENT_VERSION
import infra.database.connection as db
from infra.database.schema import init_raw_db

NEW_GRID = {"bpm":120., "first_beat_ms":271., "beat_times_ms":[271.,771.,1271.,1871.,2471.], "source":"analysis"}


def rhythm_result():
    return {"bpm":120., "features_extra": {
        "beat_positions":[.271,.771,1.271,1.871,2.471], "playback_grid":NEW_GRID,
        "playback_grid_version":VERSION, "analysis_components":{"rhythm":GRID_COMPONENT_VERSION},
    }}


@pytest.fixture
def library(tmp_path, monkeypatch):
    engine = db.create_library_engine(f"duckdb:///{tmp_path / 'grids.duckdb'}")
    init_raw_db(engine)
    monkeypatch.setattr(GridCandidateService,"rekordbox",lambda *args,**kwargs: None)
    with Session(engine) as session:
        yield session
    engine.dispose()


def add_track(session, tmp_path, source):
    path = tmp_path / f"{source}.wav"
    path.write_bytes(b"unchanged audio")
    track = Track(filepath=str(path),title="Keep title",artist="Keep artist",genre="House",duration=60.,bpm=121.)
    session.add(track); session.flush()
    analysis = TrackAnalysis(track_id=track.id,features_extra_json=json.dumps({"analysis_components":{"rhythm":"rhythm-v3","key":"key-v1"},"key_strength":.8}))
    analysis.beat_positions = [.32,.82,1.32]
    analysis.waveform_peaks = [.1,.8]
    session.add(analysis)
    session.add(TrackEmbedding(track_id=track.id,embedding_json=json.dumps([.1]*200),model_name="keep-model"))
    if source is not None:
        session.add(TrackPerformanceMetadata(track_id=track.id,revision=3,
            cue_points_json='[{"slot":0,"position_ms":321,"label":"keep cue"}]',
            loops_json='[{"id":"loop","start_ms":1000,"end_ms":3000}]',
            beat_grid_json=json.dumps({"bpm":121,"first_beat_ms":320,"source":source})))
    session.commit(); session.refresh(track)
    return track.id


def test_batch_replaces_saved_analysis_grid_and_preserves_other_data(library,tmp_path):
    ids = {source:add_track(library,tmp_path,source) for source in ("analysis","manual","rekordbox",None)}
    before = {source: library.get(TrackPerformanceMetadata,id).model_dump() for source,id in ids.items() if source}
    def analyze(path,features):
        assert features == ["rhythm"]
        return rhythm_result(),.01
    service=AnalysisJobService(library.bind,str(tmp_path / "jobs.sqlite3"),analyze)
    library.rollback()
    try:
        assert service.plan(features=["rhythm"])["selected_tracks"] == 4
        job=service.start(features=["rhythm"],workers=1)
        service._thread.join(5)
        assert not service.is_running
        assert service.status(job["id"])["counts"]["completed"] == 4
        library.expire_all()
        for source,id in ids.items():
            metadata=PerformanceMetadataAppService(library).get(id)
            if source in ("analysis",None):
                assert metadata["beat_grid"]["beat_times_ms"] == NEW_GRID["beat_times_ms"]
            if source:
                stored=library.get(TrackPerformanceMetadata,id).model_dump()
                for field in ("cue_points_json","loops_json"):
                    assert stored[field] == before[source][field]
                if source != "analysis":
                    assert stored == before[source]
                else:
                    assert stored["revision"] == before[source]["revision"] + 1
            assert library.get(Track,id).title == "Keep title"
            assert library.get(TrackEmbedding,id).model_name == "keep-model"
            analysis=library.get(TrackAnalysis,id)
            assert analysis.features_extra["key_strength"] == .8
            assert analysis.features_extra["analysis_components"]["key"] == "key-v1"
            assert analysis.waveform_peaks == pytest.approx([.1,.8],abs=.005)
        library.rollback()
        assert service.plan(features=["rhythm"])["selected_tracks"] == 0
    finally:
        service.shutdown()


def test_manual_edit_committed_during_batch_is_preserved(library,tmp_path):
    id=add_track(library,tmp_path,"analysis")
    entered,release=threading.Event(),threading.Event()
    def analyze(*_):
        entered.set(); assert release.wait(5)
        return rhythm_result(),.01
    service=AnalysisJobService(library.bind,str(tmp_path / "jobs.sqlite3"),analyze)
    library.rollback()
    try:
        job=service.start(features=["rhythm"],workers=1)
        assert entered.wait(3)
        row=library.get(TrackPerformanceMetadata,id)
        row.beat_grid_json='{"bpm":125,"first_beat_ms":200,"source":"manual"}'
        row.revision += 1
        library.add(row); library.commit()
        release.set(); service._thread.join(5)
        library.expire_all()
        assert service.status(job["id"])["counts"]["completed"] == 1
        row=library.get(TrackPerformanceMetadata,id)
        assert json.loads(row.beat_grid_json)["first_beat_ms"] == 200
        assert row.revision == 4
    finally:
        release.set(); service.shutdown()


def test_regular_reimport_also_refreshes_saved_automatic_grid(library,tmp_path):
    from infra.repositories.ingestion_repository import IngestionRepository
    id=add_track(library,tmp_path,"analysis")
    track=library.get(Track,id)
    IngestionRepository().save_track_result(library,{
        "filepath":track.filepath,"title":track.title,"artist":track.artist,"duration":60.,
        "analysis_level":"full",**rhythm_result(),
    })
    library.expire_all()
    row=library.get(TrackPerformanceMetadata,id)
    assert json.loads(row.beat_grid_json)["beat_times_ms"] == NEW_GRID["beat_times_ms"]
    assert row.revision == 4


def test_rekordbox_cache_invalidates_old_timing_policy(library,tmp_path,monkeypatch):
    import hashlib
    from app.services.grid_candidate_service import audio_fingerprint
    from infra import rekordbox_grid,rekordbox_timing
    monkeypatch.undo()
    id=add_track(library,tmp_path,None)
    track=library.get(Track,id)
    analysis_path=tmp_path / "ANLZ0000.DAT"; analysis_path.write_bytes(b"PQTZ fixture")
    monkeypatch.setattr(rekordbox_grid,"find_analysis",lambda _: (analysis_path,"external-1"))
    calls=[]
    original=BeatGrid(bpm=120,first_beat_ms=321,beat_times_ms=[321,821,1421],beat_numbers=[4,1,2],source="rekordbox")
    monkeypatch.setattr(rekordbox_grid,"read_grid",lambda _: calls.append(1) or original)
    monkeypatch.setattr(rekordbox_timing,"timing_offset_ms",lambda _: 50.)
    stat=analysis_path.stat()
    old_fingerprint=hashlib.sha256(json.dumps([str(analysis_path),stat.st_size,stat.st_mtime_ns,audio_fingerprint(track.filepath)]).encode()).hexdigest()
    service=GridCandidateService(library)
    service._cache(track,original,old_fingerprint,{})
    updated=service.rekordbox(track)
    assert updated.beat_times_ms == [271,771,1371]
    assert service.rekordbox(track) == updated
    assert calls == [1]

def test_grid_job_http_plan_pause_resume_and_request_validation(library,tmp_path,monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from api.routers import performance_metadata as routes
    ids=[add_track(library,tmp_path,source) for source in ("analysis",None)]
    entered,release=threading.Event(),threading.Event()
    calls=[]
    def analyze(path,features):
        calls.append(path)
        if len(calls)==1:
            entered.set(); assert release.wait(5)
        return rhythm_result(),.01
    service=AnalysisJobService(library.bind,str(tmp_path / "http-jobs.sqlite3"),analyze)
    monkeypatch.setattr(routes,"analysis_job_service",service)
    app=FastAPI(); app.include_router(routes.router)
    library.rollback()
    try:
        with TestClient(app) as client:
            assert client.post("/api/grid-jobs",json={"features":["embedding"]}).status_code == 422
            assert client.post("/api/grid-jobs/plan",json={"track_ids":[ids[0]]}).json()["selected_tracks"] == 1
            assert client.post("/api/grid-jobs/plan",json={}).json()["selected_tracks"] == 2
            started=client.post("/api/grid-jobs",json={})
            assert started.status_code == 200, started.text
            job_id=started.json()["id"]
            assert entered.wait(3)
            assert client.post("/api/grid-jobs",json={}).status_code == 409
            assert client.post(f"/api/grid-jobs/{job_id}/pause",json={}).status_code == 200
            release.set(); service._thread.join(5)
            status=client.get("/api/grid-jobs").json()
            assert status["status"] == "paused" and status["counts"]["completed"] == 1
            assert client.post(f"/api/grid-jobs/{job_id}/resume",json={}).status_code == 200
            service._thread.join(5)
            status=client.get("/api/grid-jobs").json()
            assert status["status"] == "completed" and status["counts"]["completed"] == 2
            assert client.post("/api/grid-jobs/plan",json={}).json()["selected_tracks"] == 0
            assert client.post("/api/grid-jobs/plan",json={"only_outdated":False}).json()["selected_tracks"] == 2
            assert client.post(f"/api/grid-jobs/{job_id}/unknown",json={}).status_code == 409
    finally:
        release.set(); service.shutdown()

