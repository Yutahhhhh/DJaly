"""Rhythm-only analysis with bounded decode, process lifetime, and concurrency."""
import multiprocessing
import queue
import threading

MAX_SECONDS = 1800
TIMEOUT_SECONDS = 120
_workers = threading.BoundedSemaphore(1)


class GridAnalysisError(ValueError):
    def __init__(self, message: str, status_code: int = 422):
        super().__init__(message)
        self.status_code = status_code


def _extract(filepath: str) -> dict:
    import numpy as np
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
    if not np.isfinite(ticks).all() or len(ticks) < 2:
        raise ValueError("The rhythm analyzer found no usable beats")
    return {"bpm": float(bpm), "ticks": ticks.tolist(), "confidence": float(confidence)}


def _worker(filepath: str, output) -> None:
    try:
        output.put((True, _extract(filepath)))
    except Exception as exc:
        output.put((False, str(exc)))


def analyze_grid(filepath: str) -> dict:
    if not _workers.acquire(blocking=False):
        raise GridAnalysisError("Another grid analysis is running; retry when it completes", 429)
    context = multiprocessing.get_context("spawn")
    output = context.Queue(maxsize=1)
    process = context.Process(target=_worker, args=(filepath, output), daemon=True)
    try:
        process.start()
        try:
            ok, result = output.get(timeout=TIMEOUT_SECONDS)
        except queue.Empty as exc:
            raise GridAnalysisError("Grid analysis timed out", 504) from exc
        if not ok:
            raise GridAnalysisError("Grid analysis failed: " + result)
        return result
    finally:
        if process.pid:
            process.join(timeout=1)
            if process.is_alive():
                process.terminate()
                process.join(timeout=2)
            if process.is_alive():
                process.kill()
                process.join(timeout=2)
        output.close()
        _workers.release()
