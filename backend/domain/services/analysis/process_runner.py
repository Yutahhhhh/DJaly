"""Run native DSP in disposable, deadline-bounded spawn workers."""
import multiprocessing
import time
import os
import sys
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor
from .progress import progress_sink


def _worker(send, function, args):
    try:
        with progress_sink(lambda event: send.send(("progress", event))):
            send.send((True, function(*args)))
    except BaseException as exc:
        try:
            send.send((False, f"{type(exc).__name__}: {exc}"))
        except (OSError, EOFError):
            pass  # The parent already timed out or cancelled and closed its pipe.
    finally:
        send.close()


def run_isolated(function, args=(), timeout=600, cancel_event=None, on_progress=None):
    context = multiprocessing.get_context("spawn")
    receive, send = context.Pipe(duplex=False)
    process = context.Process(target=_worker, args=(send, function, args), daemon=True)
    try:
        process.start()
        send.close()
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if cancel_event is not None and cancel_event.is_set():
                raise RuntimeError("Analysis cancelled")
            if receive.poll(min(.1, max(0, deadline - time.monotonic()))):
                try:
                    ok, result = receive.recv()
                except EOFError as exc:
                    raise RuntimeError("Analysis worker exited without a result") from exc
                if ok == "progress":
                    if on_progress:
                        # An observer failure must not lose a valid analysis.
                        try:
                            on_progress(result)
                        except Exception:
                            pass
                    continue
                if not ok:
                    raise RuntimeError(result)
                return result
            if not process.is_alive():
                raise RuntimeError(f"Analysis worker exited (code {process.exitcode})")
        raise TimeoutError(f"Analysis timed out after {timeout} seconds")
    finally:
        send.close()
        receive.close()
        if process.pid:
            process.join(timeout=.2)
            if process.is_alive():
                if sys.platform == "win32":
                    # Include a decoder still owned by this specific worker.
                    try:
                        subprocess.run([os.path.join(os.environ["SystemRoot"], "System32", "taskkill.exe"),
                                        "/PID", str(process.pid), "/T", "/F"],
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                       timeout=5, creationflags=subprocess.CREATE_NO_WINDOW)
                    except (OSError, subprocess.TimeoutExpired):
                        pass
                process.terminate()
                process.join(timeout=2)
            if process.is_alive():
                process.kill()
                process.join(timeout=2)
            if not process.is_alive():
                process.close()


class AnalysisExecutor(ThreadPoolExecutor):
    """A stuck native call cannot occupy a pool slot indefinitely."""
    def __init__(self, *args, task_timeout=570, **kwargs):
        super().__init__(*args, **kwargs)
        self.task_timeout = task_timeout
        self._cancel_event = threading.Event()

    def submit(self, fn, /, *args, **kwargs):
        if kwargs:
            raise TypeError("Analysis workers accept positional arguments only")
        return super().submit(run_isolated, fn, args, self.task_timeout, self._cancel_event)

    def shutdown(self, wait=True, *, cancel_futures=False):
        if cancel_futures:
            self._cancel_event.set()
        return super().shutdown(wait=wait, cancel_futures=cancel_futures)

    def submit_with_progress(self, fn, /, *args, on_progress):
        return super().submit(run_isolated, fn, args, self.task_timeout,
                              self._cancel_event, on_progress)
