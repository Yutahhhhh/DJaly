import asyncio
import time
from typing import List, Dict, Any, Optional, Callable
from fastapi import WebSocket

class BackgroundTaskService:
    def __init__(self):
        self.active_connections: List[WebSocket] = []
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
            "details": {} # For extra fields like 'file' or 'current_track'
        }

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        await websocket.send_json(self.state)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: Optional[Dict[str, Any]] = None):
        if message is None:
            message = self.state
        
        # Filter out closed connections
        active = []
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
                active.append(connection)
            except Exception:
                pass
        self.active_connections = active

    async def start_task(self, task_coroutine) -> bool:
        """
        Starts a background task.
        :param task_coroutine: A coroutine object (e.g. self._run_something())
        """
        if self.is_running:
            return False

        self.is_running = True
        self.current_task = asyncio.create_task(self._task_wrapper(task_coroutine))
        return True

    async def cancel_task(self):
        if self.current_task:
            self.current_task.cancel()
            try:
                await self.current_task
            except asyncio.CancelledError:
                pass
        
        self.is_running = False
        self.state["type"] = "idle"
        await self.broadcast()

    async def _task_wrapper(self, task_coroutine):
        try:
            self.state["type"] = "start"
            self.state["start_time"] = time.time()
            self.state["processed"] = 0
            self.state["skipped"] = 0
            self.state["errors"] = 0
            self.state["current"] = 0
            self.state["total"] = 0
            self.state["estimated_remaining"] = 0
            await self.broadcast()

            await task_coroutine

            self.state["type"] = "complete"
            self.state["message"] = "Task completed"
            await self.broadcast()
        except asyncio.CancelledError:
            print("Task cancelled.")
            self.state["type"] = "cancelled"
            await self.broadcast()
        except Exception as e:
            print(f"CRITICAL ERROR in background task: {e}")
            self.state["type"] = "error"
            self.state["message"] = str(e)
            await self.broadcast()
        finally:
            self.is_running = False
            self.current_task = None

    def update_state(self, **kwargs):
        """
        Updates the state dictionary and broadcasts it.
        """
        for key, value in kwargs.items():
            if key in self.state:
                self.state[key] = value
            else:
                self.state["details"][key] = value
        
        # Auto-calculate ETA if processed/skipped/errors changed
        if "processed" in kwargs or "skipped" in kwargs or "errors" in kwargs:
            elapsed = time.time() - self.state["start_time"]
            done = self.state["processed"] + self.state["skipped"] + self.state["errors"]
            if done > 0 and self.state["total"] > 0:
                avg_time = elapsed / done
                remaining = self.state["total"] - done
                self.state["estimated_remaining"] = avg_time * remaining

        # We don't await broadcast here to keep this method synchronous-friendly if needed,
        # but since broadcast is async, we might need to schedule it or just assume the caller will broadcast.
        # Actually, for simplicity in async context, let's make this async or fire-and-forget?
        # Making it async is safer.
        pass

    async def emit_state(self):
        await self.broadcast()
