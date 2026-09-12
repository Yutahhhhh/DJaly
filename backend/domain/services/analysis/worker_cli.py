"""Restricted JSON-line entry point for packaged analysis workers."""
import json
import sys

from .process_runner import _PROTOCOL_PREFIX
from .progress import progress_sink


def _send(message):
    sys.stdout.write(
        _PROTOCOL_PREFIX
        + json.dumps(message, ensure_ascii=False, allow_nan=False, default=_json_default)
        + "\n"
    )
    sys.stdout.flush()


def _json_default(value):
    if hasattr(value, "tolist"):
        return value.tolist()
    if hasattr(value, "item"):
        return value.item()
    raise TypeError(f"Analysis result contains unsupported type: {type(value).__name__}")


def _resolve(operation):
    # Do not accept arbitrary module/function names from the command line.
    # Only analysis operations used by the application are exposed.
    if operation == "track":
        from ingest import analyze_track_file
        return analyze_track_file
    if operation == "components":
        from app.services.analysis_job_service import analyze_components
        return analyze_components
    if operation == "rhythm-grid":
        from domain.services.analysis.rhythm_grid import _extract
        return _extract
    if operation == "light-diagnostic":
        from light_analysis_diagnostic import analyze_file
        return analyze_file
    if operation == "probe":
        from domain.services.analysis.process_runner import worker_probe
        return worker_probe
    raise ValueError(f"Unknown analysis worker operation: {operation}")


def run():
    try:
        line = sys.stdin.readline(16 * 1024 * 1024)
        if not line or not line.endswith("\n"):
            raise ValueError("Analysis worker request is missing or too large")
        request = json.loads(line)
        if request.get("version") != 1 or not isinstance(request.get("args"), list):
            raise ValueError("Unsupported analysis worker request")
        _send({
            "type": "progress",
            "event": {"stage": "worker_ready", "label": "解析ワーカーを開始しました"},
        })
        function = _resolve(request.get("operation"))
        with progress_sink(lambda event: _send({"type": "progress", "event": event})):
            value = function(*request["args"])
        _send({"type": "result", "ok": True, "value": value})
        return 0
    except BaseException as exc:
        try:
            _send({
                "type": "result",
                "ok": False,
                "error": {"type": type(exc).__name__, "message": str(exc)},
            })
        except BaseException:
            pass
        return 1
