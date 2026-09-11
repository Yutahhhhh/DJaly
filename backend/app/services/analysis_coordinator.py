"""Process-wide admission control for native audio analysis."""
from __future__ import annotations

import threading
import uuid


class AnalysisCoordinator:
    def __init__(self):
        self._capacity = threading.Lock()
        self._state = threading.Lock()
        self._token: str | None = None
        self._owner: str | None = None

    def acquire(self, owner: str, *, wait: bool = False) -> str | None:
        if not self._capacity.acquire(blocking=wait):
            return None
        token = uuid.uuid4().hex
        with self._state:
            self._token = token
            self._owner = owner
        return token

    def release(self, token: str) -> None:
        with self._state:
            if token != self._token:
                return
            self._token = None
            self._owner = None
        self._capacity.release()

    @property
    def owner(self) -> str | None:
        with self._state:
            return self._owner


analysis_coordinator = AnalysisCoordinator()
