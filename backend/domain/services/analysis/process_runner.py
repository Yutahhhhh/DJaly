"""Run native DSP in disposable, deadline-bounded workers."""
from collections import deque
import json
import multiprocessing
import time
import os
from pathlib import Path
import queue
import sys
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor
from .progress import progress_sink


_PROTOCOL_PREFIX = "PLUMDECK_ANALYSIS_WORKER_V1:"
_WORKER_OPERATIONS = {
    ("ingest", "analyze_track_file"): "track",
    ("app.services.analysis_job_service", "analyze_components"): "components",
    ("domain.services.analysis.rhythm_grid", "_extract"): "rhythm-grid",
    ("light_analysis_diagnostic", "analyze_file"): "light-diagnostic",
    (__name__, "worker_probe"): "probe",
}


def worker_probe(value, delay=0):
    """Small packaged-worker probe used by regression tests."""
    from .progress import report
    report("probe", "解析ワーカーとの通信を確認しています")
    if delay:
        time.sleep(delay)
    return value


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


def _run_multiprocessing(function, args, timeout, cancel_event, on_progress):
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


def _worker_command():
    if getattr(sys, "frozen", False):
        return [sys.executable, "--analysis-worker"]
    server = Path(__file__).resolve().parents[3] / "server.py"
    return [sys.executable, str(server), "--analysis-worker"]


def _terminate_subprocess(process):
    if process.poll() is not None:
        return
    try:
        process.wait(timeout=.5)
        return
    except subprocess.TimeoutExpired:
        pass
    if sys.platform == "win32":
        try:
            subprocess.run([
                os.path.join(os.environ["SystemRoot"], "System32", "taskkill.exe"),
                "/PID", str(process.pid), "/T", "/F",
            ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5,
                creationflags=subprocess.CREATE_NO_WINDOW)
        except (KeyError, OSError, subprocess.TimeoutExpired):
            pass
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=2)


def _run_subprocess_worker(function, args, timeout, cancel_event, on_progress):
    key = (getattr(function, "__module__", ""), getattr(function, "__qualname__", ""))
    operation = _WORKER_OPERATIONS.get(key)
    if operation is None:
        raise TypeError(f"Analysis function is not available to the packaged worker: {key[0]}.{key[1]}")

    # PyInstaller 6.9+ deliberately lets same-executable worker subprocesses
    # reuse the already-unpacked one-file bundle. Do not reset that environment.
    environment = os.environ.copy()
    environment.pop("PYINSTALLER_RESET_ENVIRONMENT", None)
    creationflags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    process = subprocess.Popen(
        _worker_command(), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace",
        bufsize=1, env=environment, creationflags=creationflags,
    )
    messages = queue.Queue()
    output_tail = deque(maxlen=30)

    def read_output():
        try:
            for line in process.stdout:
                messages.put(line)
        finally:
            messages.put(None)

    reader = threading.Thread(
        target=read_output, daemon=True,
        name=f"plumdeck-analysis-worker-{process.pid}-output",
    )
    reader.start()
    deadline = time.monotonic() + timeout
    try:
        request = json.dumps({"version": 1, "operation": operation, "args": list(args)},
                             ensure_ascii=False, allow_nan=False)
        try:
            process.stdin.write(request + "\n")
            process.stdin.flush()
            process.stdin.close()
        except (BrokenPipeError, OSError) as exc:
            raise RuntimeError("Analysis worker closed its request pipe during startup") from exc

        while time.monotonic() < deadline:
            if cancel_event is not None and cancel_event.is_set():
                raise RuntimeError("Analysis cancelled")
            remaining = max(0, deadline - time.monotonic())
            try:
                line = messages.get(timeout=min(.1, remaining))
            except queue.Empty:
                if process.poll() is not None and not reader.is_alive():
                    detail = " | ".join(output_tail)
                    suffix = f": {detail}" if detail else ""
                    raise RuntimeError(f"Analysis worker exited (code {process.returncode}){suffix}")
                continue
            if line is None:
                detail = " | ".join(output_tail)
                suffix = f": {detail}" if detail else ""
                raise RuntimeError(f"Analysis worker exited (code {process.poll()}) without a result{suffix}")
            stripped = line.rstrip("\r\n")
            if not stripped.startswith(_PROTOCOL_PREFIX):
                if stripped:
                    output_tail.append(stripped)
                continue
            try:
                message = json.loads(stripped[len(_PROTOCOL_PREFIX):])
            except json.JSONDecodeError as exc:
                raise RuntimeError("Analysis worker returned an invalid protocol message") from exc
            if message.get("type") == "progress":
                if on_progress:
                    try:
                        on_progress(message["event"])
                    except Exception:
                        pass
                continue
            if message.get("type") != "result":
                raise RuntimeError("Analysis worker returned an unknown protocol message")
            if not message.get("ok"):
                error = message.get("error") or {}
                raise RuntimeError(f"{error.get('type', 'RuntimeError')}: {error.get('message', 'Analysis failed')}")
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                pass
            return message.get("value")
        raise TimeoutError(f"Analysis timed out after {timeout} seconds")
    finally:
        _terminate_subprocess(process)
        reader.join(timeout=1)
        if process.stdout is not None:
            process.stdout.close()


def run_isolated(function, args=(), timeout=600, cancel_event=None, on_progress=None):
    # multiprocessing.spawn can stall before entering the Python target when a
    # one-file PyInstaller server is itself managed as a Tauri sidecar. A plain
    # explicit subprocess with a stable CLI protocol avoids that bootstrapping
    # path while preserving hard deadlines and per-track process isolation.
    if ((sys.platform == "win32" and getattr(sys, "frozen", False))
            or os.environ.get("PLUMDECK_FORCE_SUBPROCESS_WORKER") == "1"):
        return _run_subprocess_worker(function, args, timeout, cancel_event, on_progress)
    return _run_multiprocessing(function, args, timeout, cancel_event, on_progress)


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
