"""Live stages complement durable batch counts; no database writes per event."""
import threading
import time


class AnalysisProgress:
    def __init__(self):
        self._lock = threading.Lock()
        self._items = {}

    def update(self, key, filepath, event):
        with self._lock:
            previous = self._items.get(key, {})
            started = previous.get("started_at") if previous.get("filepath") == filepath else None
            self._items[key] = {**event, "filepath": filepath,
                                "started_at": started or time.time()}

    def get(self, key):
        with self._lock:
            return dict(self._items[key]) if key in self._items else None

    def clear(self, key):
        with self._lock:
            self._items.pop(key, None)


analysis_progress = AnalysisProgress()
