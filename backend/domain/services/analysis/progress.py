"""Worker-local progress sink. Only actual work boundaries emit a stage."""
from contextlib import contextmanager
from contextvars import ContextVar

_sink = ContextVar("analysis_progress", default=None)


@contextmanager
def progress_sink(callback):
    token = _sink.set(callback)
    try:
        yield
    finally:
        _sink.reset(token)


def report(stage: str, label: str):
    callback = _sink.get()
    if callback:
        callback({"stage": stage, "label": label})
