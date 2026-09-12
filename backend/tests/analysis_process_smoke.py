"""Dependency-free smoke checks for worker failure recovery."""
import os
import time
import unittest
from domain.services.analysis.process_runner import run_isolated, AnalysisExecutor, worker_probe
from domain.services.analysis.progress import report


def echo(value):
    return value


def crash():
    os._exit(7)


def hang():
    time.sleep(30)


def progressing():
    report("decode", "音源を読み込み中")
    time.sleep(.05)
    report("rhythm", "BPMを解析中")
    return 126


def endless_progress():
    while True:
        report("rhythm", "解析中")
        time.sleep(.01)


class ProcessSmoke(unittest.TestCase):
    def test_result(self):
        self.assertEqual(run_isolated(echo, ({"ok": True},), 5), {"ok": True})

    def test_crash_releases_worker(self):
        started = time.monotonic()
        with self.assertRaises(RuntimeError):
            run_isolated(crash, timeout=5)
        self.assertLess(time.monotonic() - started, 5)
        self.assertEqual(run_isolated(echo, (42,), 5), 42)

    def test_timeout_releases_worker(self):
        with self.assertRaises(TimeoutError):
            run_isolated(hang, timeout=.3)
        self.assertEqual(run_isolated(echo, (42,), 5), 42)

    def test_executor_survives_crash(self):
        with AnalysisExecutor(max_workers=1) as pool:
            with self.assertRaises(RuntimeError):
                pool.submit(crash).result(timeout=5)
            self.assertEqual(pool.submit(echo, 42).result(timeout=5), 42)

    def test_progress_is_delivered_before_result(self):
        stages = []
        with AnalysisExecutor(max_workers=1) as pool:
            future = pool.submit_with_progress(progressing, on_progress=lambda event: stages.append((event["stage"], time.monotonic())))
            self.assertEqual(future.result(timeout=5), 126)
        self.assertEqual([stage for stage, _ in stages], ["decode", "rhythm"])
        self.assertGreater(stages[1][1] - stages[0][1], .02)

    def test_progress_does_not_reset_deadline(self):
        with self.assertRaises(TimeoutError):
            run_isolated(endless_progress, timeout=.3, on_progress=lambda _: None)
        self.assertEqual(run_isolated(echo, (42,), 5), 42)

    def test_broken_observer_does_not_fail_analysis(self):
        def broken(_event):
            raise RuntimeError("UI disconnected")
        self.assertEqual(run_isolated(progressing, timeout=5, on_progress=broken), 126)

    def test_explicit_worker_subcommand_runs_from_executor_thread(self):
        previous = os.environ.get("PLUMDECK_FORCE_SUBPROCESS_WORKER")
        os.environ["PLUMDECK_FORCE_SUBPROCESS_WORKER"] = "1"
        stages = []
        value = {"path": "C:/音楽/テラス・コンガ.mp3"}
        try:
            with AnalysisExecutor(max_workers=1, task_timeout=10) as pool:
                result = pool.submit_with_progress(
                    worker_probe, value,
                    on_progress=lambda event: stages.append(event["stage"]),
                ).result(timeout=15)
        finally:
            if previous is None:
                os.environ.pop("PLUMDECK_FORCE_SUBPROCESS_WORKER", None)
            else:
                os.environ["PLUMDECK_FORCE_SUBPROCESS_WORKER"] = previous
        self.assertEqual(result, value)
        self.assertEqual(stages, ["worker_ready", "probe"])

    def test_explicit_worker_timeout_releases_process(self):
        previous = os.environ.get("PLUMDECK_FORCE_SUBPROCESS_WORKER")
        os.environ["PLUMDECK_FORCE_SUBPROCESS_WORKER"] = "1"
        try:
            with self.assertRaises(TimeoutError):
                run_isolated(worker_probe, (None, 30), timeout=.3)
            self.assertEqual(run_isolated(worker_probe, (42,), timeout=10), 42)
        finally:
            if previous is None:
                os.environ.pop("PLUMDECK_FORCE_SUBPROCESS_WORKER", None)
            else:
                os.environ["PLUMDECK_FORCE_SUBPROCESS_WORKER"] = previous


if __name__ == "__main__":
    unittest.main()
