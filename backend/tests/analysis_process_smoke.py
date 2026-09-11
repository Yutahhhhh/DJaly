"""Dependency-free smoke checks for worker failure recovery."""
import os
import time
import unittest
from domain.services.analysis.process_runner import run_isolated, AnalysisExecutor


def echo(value):
    return value


def crash():
    os._exit(7)


def hang():
    time.sleep(30)


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


if __name__ == "__main__":
    unittest.main()
