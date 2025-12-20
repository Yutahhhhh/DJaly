import asyncio
import os
import multiprocessing
from concurrent.futures import ProcessPoolExecutor
from typing import List, Dict, Any, Optional
from fastapi import WebSocket
from sqlmodel import Session, select
from config import settings
from domain.models.track import Track, TrackEmbedding
from domain.services.ingestion_domain_service import IngestionDomainService
from infra.repositories.ingestion_repository import IngestionRepository
from utils.ingestion import expand_targets, filter_and_prioritize_files
import sys
import time

def worker_init():
    try:
        sys.stdin.fileno()
    except (ValueError, AttributeError, OSError):
        sys.stdin = open(os.devnull, 'r')
    
    try:
        sys.stdout.fileno()
    except (ValueError, AttributeError, OSError):
        sys.stdout = open(os.devnull, 'w')
        
    try:
        sys.stderr.fileno()
    except (ValueError, AttributeError, OSError):
        sys.stderr = open(os.devnull, 'w')

ANALYSIS_TIMEOUT = 600.0

class IngestionAppService:
    def __init__(self):
        self.active_connections: List[WebSocket] = []
        self.is_running = False
        self.current_task: Optional[asyncio.Task] = None
        self.state = {
            "type": "idle",
            "total": 0,
            "current": 0,
            "file": "",
            "processed": 0,
            "skipped": 0,
            "errors": 0,
            "start_time": 0,
            "estimated_remaining": 0
        }
        self.executor = None
        self.db_lock = asyncio.Lock()
        self.llm_sem = asyncio.Semaphore(1)
        self.domain_service = IngestionDomainService()
        self.repository = IngestionRepository()

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        await websocket.send_json(self.state)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: Dict[str, Any]):
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception:
                pass

    async def start_ingestion(self, targets: List[str], force_update: bool = False) -> bool:
        if self.is_running:
            return False

        self.is_running = True
        self.current_task = asyncio.create_task(self._run_ingestion(targets, force_update))
        return True

    async def cancel_ingestion(self):
        if self.current_task:
            self.current_task.cancel()
            try:
                await self.current_task
            except asyncio.CancelledError:
                pass
        
        self.is_running = False
        self.state["type"] = "idle"
        await self.broadcast(self.state)

    async def _run_ingestion(self, targets: List[str], force_update: bool):
        try:
            # Notify start immediately to show loading state
            self.state["type"] = "start"
            self.state["total"] = 0
            self.state["current"] = 0
            self.state["processed"] = 0
            self.state["skipped"] = 0
            self.state["errors"] = 0
            await self.broadcast(self.state)

            expanded_files = expand_targets(targets)
            files_to_process, _ = filter_and_prioritize_files(expanded_files, force_update)
            
            total_files = len(files_to_process)
            if total_files == 0:
                self.is_running = False
                self.state["type"] = "complete"
                self.state["total"] = 0
                await self.broadcast(self.state)
                return

            self.state = {
                "type": "processing",
                "total": total_files,
                "current": 0,
                "file": "",
                "processed": 0,
                "skipped": 0,
                "errors": 0,
                "start_time": time.time(),
                "estimated_remaining": 0
            }
            await self.broadcast(self.state)

            max_workers = max(1, multiprocessing.cpu_count() - 1)
            loop = asyncio.get_running_loop()

            with ProcessPoolExecutor(max_workers=max_workers, initializer=worker_init) as executor:
                self.executor = executor
                
                for i, filepath in enumerate(files_to_process):
                    if not self.is_running:
                        break
                    
                    self.state["type"] = "progress"
                    self.state["current"] = i + 1
                    self.state["file"] = os.path.basename(filepath)
                    
                    elapsed = time.time() - self.state["start_time"]
                    if i > 0:
                        avg_time = elapsed / i
                        remaining = total_files - i
                        self.state["estimated_remaining"] = avg_time * remaining
                    
                    await self.broadcast(self.state)

                    try:
                        result = await self.domain_service.process_track_ingestion(
                            filepath, 
                            force_update, 
                            loop, 
                            executor, 
                            ANALYSIS_TIMEOUT, 
                            self.db_lock, 
                            save_to_db=True
                        )
                        
                        if result:
                            self.state["processed"] += 1
                        else:
                            self.state["skipped"] += 1
                            
                    except Exception as e:
                        print(f"ERROR: Ingestion failed for {filepath}: {e}")
                        self.state["errors"] += 1

            self.state["type"] = "complete"
            self.state["file"] = ""
            await self.broadcast(self.state)
            
        except asyncio.CancelledError:
            print("Ingestion cancelled.")
            self.state["type"] = "cancelled"
            await self.broadcast(self.state)
        except Exception as e:
            print(f"CRITICAL ERROR in ingestion loop: {e}")
            self.state["type"] = "error"
            self.state["message"] = str(e)
            await self.broadcast(self.state)
        finally:
            self.is_running = False
            self.current_task = None
            self.executor = None

# Global Instance
ingestion_app_service = IngestionAppService()
