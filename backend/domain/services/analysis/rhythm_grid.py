"""Rhythm-only analysis with bounded decode, process lifetime, and concurrency."""
import sys
import threading
from .process_runner import run_isolated

MAX_SECONDS = 1800
TIMEOUT_SECONDS = 120
_workers = threading.BoundedSemaphore(1)


class GridAnalysisError(ValueError):
    def __init__(self, message: str, status_code: int = 422):
        super().__init__(message)
        self.status_code = status_code


def _extract(filepath: str) -> dict:
    import numpy as np
    if sys.platform == "win32":
        from .portable import PortableAudioAnalyzer
        from .light_grid import analyze
        analyzer = PortableAudioAnalyzer()
        audio = analyzer._load_grid_audio(filepath)
        bpm, ticks, confidence = analyze(audio)
        if not np.isfinite(ticks).all() or len(ticks) < 2:
            raise ValueError("The rhythm analyzer found no usable beats")
        return {"bpm": float(bpm), "ticks": ticks.tolist(), "confidence": float(confidence)}
    import essentia.standard as es

    # EasyLoader limits decoding before allocating a whole, possibly hours-long file.
    audio = es.EasyLoader(filename=filepath, sampleRate=44100, startTime=0,
                          endTime=MAX_SECONDS + 1, replayGain=0)()
    if len(audio) > MAX_SECONDS * 44100:
        raise ValueError("Grid analysis supports audio up to 30 minutes")
    if len(audio) < 5 * 44100 or not np.isfinite(audio).all():
        raise ValueError("Grid analysis needs at least five seconds of valid audio")
    if float(np.max(np.abs(audio))) < 1e-6:
        raise ValueError("No audible signal available for beat analysis")
    bpm, ticks, confidence, _, _ = es.RhythmExtractor2013(method="multifeature")(audio)
    from .beat_alignment import align_beats
    ticks = align_beats(audio, ticks, 44100)
    if not np.isfinite(ticks).all() or len(ticks) < 2:
        raise ValueError("The rhythm analyzer found no usable beats")
    return {"bpm": float(bpm), "ticks": ticks.tolist(), "confidence": float(confidence)}


def analyze_grid(filepath: str) -> dict:
    if not _workers.acquire(timeout=TIMEOUT_SECONDS + 5):
        raise GridAnalysisError("Grid analysis queue timed out; retry shortly", 503)
    try:
        try:
            return run_isolated(_extract, (filepath,), TIMEOUT_SECONDS)
        except TimeoutError as exc:
            raise GridAnalysisError("Grid analysis timed out", 504) from exc
        except RuntimeError as exc:
            raise GridAnalysisError("Grid analysis failed: " + str(exc)) from exc
    finally:
        _workers.release()
