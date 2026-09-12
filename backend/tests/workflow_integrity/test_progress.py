import asyncio
import json

from app.services.analysis_progress import AnalysisProgress
from app.services.ingestion_app_service import IngestionAppService


def test_live_stage_retains_elapsed_time_and_can_be_cleared():
    progress = AnalysisProgress()
    progress.update("batch", "song.mp3", {"stage": "decode", "label": "読み込み"})
    first = progress.get("batch")
    progress.update("batch", "song.mp3", {"stage": "rhythm", "label": "BPM"})
    assert progress.get("batch")["started_at"] == first["started_at"]
    assert progress.get("batch")["label"] == "BPM"
    first["label"] = "mutated"
    assert progress.get("batch")["label"] == "BPM"
    progress.clear("batch")
    assert progress.get("batch") is None


def test_startup_milestone_has_a_machine_readable_prefix(capsys):
    from startup_progress import report
    report("database", "楽曲データベースを準備しています", 3)
    prefix, payload = capsys.readouterr().out.strip().split(":", 1)
    assert prefix == "PLUMDECK_STARTUP"
    assert json.loads(payload) == {"stage": "database", "label": "楽曲データベースを準備しています", "completed": 3, "total": 5}


def test_explorer_shows_current_stage_and_removes_finished_track(monkeypatch):
    from app.services import ingestion_app_service as module
    monkeypatch.setattr(module, "expand_targets", lambda values: values)
    monkeypatch.setattr(module, "filter_and_prioritize_files", lambda values, *_: (values, 0))
    service = IngestionAppService()
    observed = []

    class Domain:
        async def process_track_ingestion(self, filepath, *_args, on_progress, **_kwargs):
            on_progress({"stage": "rhythm", "label": "BPMを解析しています"})
            await asyncio.sleep(.01)
            observed.append(service.state["details"]["active_progress"][filepath])
            return {"analysis_level": "light"}

    service.domain_service = Domain()
    asyncio.run(service._run_ingestion(["fixture.mp3"], False, "light"))
    assert observed == ["BPMを解析しています"]
    assert service.state["details"]["active_progress"] == {}
