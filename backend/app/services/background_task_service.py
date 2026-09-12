import asyncio
import time
import uuid
import infra.database.connection as db_connection
from typing import List, Dict, Any, Optional, Callable

class BackgroundTaskService:
    def __init__(self):
        self.active_connections: List[Any] = []
        self.is_running = False
        self.current_task: Optional[asyncio.Task] = None
        self.state = {
            "type": "idle",
            "total": 0,
            "current": 0,
            "message": "",
            "processed": 0,
            "skipped": 0,
            "errors": 0,
            "start_time": 0,
            "estimated_remaining": 0,
            "run_id": None,
            "revision": 0,
            "details": {} # For extra fields like 'file' or 'current_track'
        }

    async def connect(self, websocket: Any):
        await websocket.accept()
        self.active_connections.append(websocket)
        await websocket.send_json(self.state)

    def disconnect(self, websocket: Any):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: Optional[Dict[str, Any]] = None):
        if message is None:
            message = self.state
        
        # Filter out closed connections
        active = []
        for connection in self.active_connections:
            try:
                await asyncio.wait_for(connection.send_json(message), timeout=2)
                active.append(connection)
            except Exception:
                pass
        self.active_connections = active

    async def start_task(self, task_coroutine) -> bool:
        """
        Starts a background task.
        :param task_coroutine: A coroutine object (e.g. self._run_something())
        """
        with db_connection._lease_lock:
            if self.is_running or db_connection._maintenance_owner is not None:
                task_coroutine.close()
                return False
            self.is_running = True
            self.state.update({
                "type": "start",
                "run_id": uuid.uuid4().hex,
                "revision": 0,
                "start_time": time.time(),
                "processed": 0,
                "skipped": 0,
                "errors": 0,
                "current": 0,
                "total": 0,
                "estimated_remaining": 0,
                "message": "",
                "details": {},
            })
            self.current_task = asyncio.create_task(self._task_wrapper(task_coroutine))
            def finalize(task):
                # A task cancelled before its first step never enters the
                # wrapper's finally. Close the unawaited coroutine and clear
                # ownership so an immediate retry can start.
                task_coroutine.close()
                if self.current_task is task:
                    self.is_running = False
                    self.current_task = None
            self.current_task.add_done_callback(finalize)
        await self.broadcast()
        return True

    async def cancel_task(self):
        task = self.current_task
        if task:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            # _task_wrapper normally publishes this state. Keep this guard for
            # implementations that finish between the cancel request and await.
            if self.state["type"] != "cancelled":
                self.update_state(type="cancelled")
                await self.broadcast()

    async def _task_wrapper(self, task_coroutine):
        try:
            await task_coroutine

            # The task may already have reported an error or cancellation.
            if self.state["type"] not in {"error", "cancelled", "complete"}:
                self.update_state(type="complete", message="Task completed")
                await self.broadcast()
        except asyncio.CancelledError:
            print("Task cancelled.")
            self.update_state(type="cancelled")
            await self.broadcast()
        except Exception as e:
            print(f"CRITICAL ERROR in background task: {e}")
            self.update_state(type="error", message=str(e))
            await self.broadcast()
        finally:
            self.is_running = False
            self.current_task = None

    def update_state(self, **kwargs):
        """
        state を更新する。ブロードキャストは呼び出し側が emit_state() で行う。
        """
        for key, value in kwargs.items():
            if key in self.state:
                self.state[key] = value
            else:
                self.state["details"][key] = value
        self.state["revision"] = int(self.state.get("revision", 0)) + 1

        # Auto-calculate ETA if processed/skipped/errors changed
        if "processed" in kwargs or "skipped" in kwargs or "errors" in kwargs:
            done = self.state["processed"] + self.state["skipped"] + self.state["errors"]
            # start_time 未設定 (0) の場合は ETA を計算しない (巨大な値になるのを防ぐ)
            if self.state["start_time"] > 0 and done > 0 and self.state["total"] > 0:
                elapsed = time.time() - self.state["start_time"]
                avg_time = elapsed / done
                remaining = max(0, self.state["total"] - done)
                self.state["estimated_remaining"] = avg_time * remaining

    async def emit_state(self):
        await self.broadcast()
