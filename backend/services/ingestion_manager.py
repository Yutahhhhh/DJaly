import asyncio
import os
import multiprocessing
from concurrent.futures import ProcessPoolExecutor
from typing import List, Dict, Any, Optional
from fastapi import WebSocket
from sqlmodel import Session, select
from config import settings
from models import Track, TrackEmbedding
from db import engine
from services.ingestion import process_track_ingestion
from services.ingestion_db import batch_save_tracks
from utils.ingestion import expand_targets, filter_and_prioritize_files
import sys

def worker_init():
    """
    Worker process initializer to handle standard streams in detached environments.
    """
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

# 解析のタイムアウト時間（秒）
ANALYSIS_TIMEOUT = 600.0

import time

class IngestionManager:
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
            "warning_count": 0
        }
        self.last_broadcast_time = 0.0
        
        # CPUコア数の取得
        try:
            if hasattr(os, "sched_getaffinity"):
                cpu_cores = len(os.sched_getaffinity(0))
            else:
                cpu_cores = multiprocessing.cpu_count()
        except:
            cpu_cores = multiprocessing.cpu_count()

        # 並列化設定
        default_workers = max(2, cpu_cores - 1)
        if settings.ENV == "dev":
             default_workers = 2

        if settings.NUM_WORKERS:
            try:
                self.max_workers = int(settings.NUM_WORKERS)
            except ValueError:
                self.max_workers = default_workers
        else:
            self.max_workers = default_workers

        print(f"IngestionManager initialized with {self.max_workers} processes (PARALLEL MODE).")
        
        self.db_lock = asyncio.Lock()
        self.llm_sem = asyncio.Semaphore(1)
        
        self.save_queue = asyncio.Queue()
        self.save_task: Optional[asyncio.Task] = None

        ctx = multiprocessing.get_context("spawn")
        self.executor = ProcessPoolExecutor(
            max_workers=self.max_workers,
            mp_context=ctx,
            initializer=worker_init
        )

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        try:
            await websocket.send_json(self.state)
        except Exception:
            self.disconnect(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: Dict[str, Any]):
        if not self.is_running and message["type"] not in ["complete", "error", "cancelled", "start"]:
            return

        if message["type"] not in ["error"]:
            self.state.update(message)
        
        if message["type"] in ["complete", "error"]:
            self.is_running = False
        
        now = time.time()
        if message["type"] in ["processing", "progress", "skip"]:
            if now - self.last_broadcast_time < 0.1:  # 100ms
                return
            self.last_broadcast_time = now

        to_remove = []
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception:
                to_remove.append(connection)
        
        for conn in to_remove:
            self.active_connections.remove(conn)

    async def start_ingestion(self, targets: List[str], force_update: bool):
        if self.is_running:
            return False

        self.is_running = True
        self.state.update({
            "type": "start",
            "total": 0,
            "current": 0,
            "file": "Initializing...",
            "processed": 0,
            "warning_count": 0
        })
        
        self.current_task = asyncio.create_task(self._process_loop(targets, force_update))
        return True

    def shutdown(self):
        print("Shutting down IngestionManager...")
        self.is_running = False
        
        if self.current_task:
            self.current_task.cancel()
        
        try:
            self.executor.shutdown(wait=False, cancel_futures=True)
            print("ProcessPoolExecutor shutdown successfully.")
        except Exception as e:
            print(f"Error shutting down executor: {e}")

    async def _db_save_loop(self):
        print("DEBUG: _db_save_loop started")
        batch = []
        last_save_time = time.time()
        BATCH_SIZE = 50
        BATCH_TIMEOUT = 2.0 

        while self.is_running or not self.save_queue.empty():
            try:
                try:
                    item = await asyncio.wait_for(self.save_queue.get(), timeout=0.5)
                    batch.append(item)
                except asyncio.TimeoutError:
                    pass
                
                now = time.time()
                if len(batch) >= BATCH_SIZE or (batch and now - last_save_time > BATCH_TIMEOUT) or (not self.is_running and batch):
                    print(f"DEBUG: Saving batch of {len(batch)} tracks...")
                    await batch_save_tracks(batch)
                    
                    for _ in batch:
                        self.save_queue.task_done()
                    
                    batch = []
                    last_save_time = now
                
                if not self.is_running and self.save_queue.empty() and not batch:
                    break
                    
            except Exception as e:
                print(f"ERROR in _db_save_loop: {e}")
                import traceback
                traceback.print_exc()
                if batch:
                    for _ in batch: self.save_queue.task_done()
                    batch = []

    async def _worker(self, worker_id: str, queue: asyncio.Queue, 
                      progress_stats: Dict[str, int], total_files: int, force_update: bool, 
                      loop: asyncio.AbstractEventLoop):
        while True:
            try:
                filepath = await queue.get()
                filename = os.path.basename(filepath)

                if not self.is_running:
                    queue.task_done()
                    break

                await self.broadcast({
                    "type": "processing",
                    "current": progress_stats["completed_tasks"] + 1,
                    "total": total_files,
                    "file": filename
                })

                try:
                    result = await process_track_ingestion(
                        filepath=filepath, 
                        force_update=force_update, 
                        loop=loop, 
                        executor=self.executor, 
                        timeout=ANALYSIS_TIMEOUT,
                        db_lock=self.db_lock, 
                        llm_sem=self.llm_sem,
                        save_to_db=False 
                    )
                    
                    progress_stats["completed_tasks"] += 1
                    
                    if result:
                        await self.save_queue.put(result)
                        
                        progress_stats["processed"] += 1
                        bpm_val = result["bpm"]
                        key_val = result.get("key", "")
                        
                        if key_val == "Unknown" or key_val == "":
                            progress_stats["warning_count"] += 1

                        await self.broadcast({
                            "type": "progress",
                            "current": progress_stats["completed_tasks"],
                            "total": total_files,
                            "file": filename,
                            "bpm": bpm_val,
                            "key": key_val
                        })
                except Exception as e:
                    print(f"[{worker_id}] Error processing {filename}: {e}")
                    progress_stats["completed_tasks"] += 1
                
                queue.task_done()

            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"[{worker_id}] Worker Exception: {e}")
                if 'filepath' in locals():
                    queue.task_done()

    async def _process_loop(self, targets: List[str], force_update: bool):
        print("DEBUG: _process_loop started (PROCESS POOL MODE)")
        workers = []
        try:
            all_files = expand_targets(targets)
            files_to_process, skipped_count = filter_and_prioritize_files(all_files, force_update)
            
            total_files = len(files_to_process)
            print(f"DEBUG: Found {len(all_files)} files. Processing {total_files} files (Skipped {skipped_count}).")
            
            await self.broadcast({
                "type": "start",
                "total": total_files
            })
            
            self.save_task = asyncio.create_task(self._db_save_loop())
            
            queue = asyncio.Queue()
            for f in files_to_process:
                queue.put_nowait(f)
            
            progress_stats = {
                "completed_tasks": 0,
                "processed": 0,
                "warning_count": 0
            }
            
            loop = asyncio.get_running_loop()
            
            for i in range(self.max_workers):
                w = asyncio.create_task(
                    self._worker(f"Worker-{i}", queue, progress_stats, total_files, force_update, loop)
                )
                workers.append(w)
            
            await queue.join()
            await self.save_queue.join()
            
            if self.save_task:
                self.save_task.cancel()
                try:
                    await self.save_task
                except asyncio.CancelledError:
                    pass
            
            await self.broadcast({
                "type": "complete",
                "processed": progress_stats["processed"],
                "total": total_files,
                "warning_count": progress_stats["warning_count"]
            })
            
        except asyncio.CancelledError:
            print("Ingestion cancelled.")
            if self.save_task:
                self.save_task.cancel()
            raise
        except Exception as e:
            print(f"Ingestion Error: {e}")
            await self.broadcast({
                "type": "error",
                "message": str(e)
            })
        finally:
            for w in workers:
                if not w.done():
                    w.cancel()
            
            self.is_running = False
            self.current_task = None

    async def cancel_ingestion(self):
        if not self.is_running:
            return False
            
        print("Cancelling ingestion...")
        self.is_running = False
        
        if self.current_task:
            self.current_task.cancel()
            try:
                await self.current_task
            except asyncio.CancelledError:
                pass
            self.current_task = None
            
        await self.broadcast({
            "type": "cancelled",
            "message": "Analysis cancelled by user."
        })
        
        self.state["type"] = "idle"
        return True

ingestion_manager = IngestionManager()