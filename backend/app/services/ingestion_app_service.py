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
from app.services.background_task_service import BackgroundTaskService
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

class IngestionAppService(BackgroundTaskService):
    def __init__(self):
        super().__init__()
        self.state.update({
            "file": ""
        })
        self.executor = None
        self.db_lock = asyncio.Lock()
        self.llm_sem = asyncio.Semaphore(1)
        self.domain_service = IngestionDomainService()
        self.repository = IngestionRepository()

    async def start_ingestion(self, targets: List[str], force_update: bool = False) -> bool:
        return await self.start_task(self._run_ingestion(targets, force_update))

    async def cancel_ingestion(self):
        await self.cancel_task()

    async def _run_ingestion(self, targets: List[str], force_update: bool):
        try:
            # Notify start immediately to show loading state
            self.update_state(
                type="start",
                total=0,
                current=0,
                processed=0,
                skipped=0,
                errors=0
            )
            await self.emit_state()

            expanded_files = expand_targets(targets)
            files_to_process, _ = filter_and_prioritize_files(expanded_files, force_update)
            
            total_files = len(files_to_process)
            if total_files == 0:
                self.update_state(type="complete", total=0)
                await self.emit_state()
                return

            self.update_state(
                type="processing",
                total=total_files,
                current=0,
                file="",
                processed=0,
                skipped=0,
                errors=0,
                start_time=time.time(),
                estimated_remaining=0
            )
            await self.emit_state()

            max_workers = max(1, multiprocessing.cpu_count() - 1)
            loop = asyncio.get_running_loop()
            
            # Concurrency control
            sem = asyncio.Semaphore(max_workers)

            async def process_single_file(filepath: str):
                async with sem:
                    # Update UI state (Best effort)
                    current_count = self.state["processed"] + self.state["skipped"] + self.state["errors"] + 1
                    self.update_state(
                        file=os.path.basename(filepath),
                        current=current_count
                    )
                    await self.emit_state()

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
                    
                    # Update progress estimation
                    self.update_state() # Recalculate ETA
                    await self.emit_state()

            with ProcessPoolExecutor(max_workers=max_workers, initializer=worker_init) as executor:
                self.executor = executor
                
                # Create tasks for all files
                tasks = [process_single_file(fp) for fp in files_to_process]
                
                # Run tasks concurrently
                try:
                    await asyncio.gather(*tasks)
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    print(f"Error in batch processing: {e}")

            self.update_state(type="complete", file="")
            await self.emit_state()
            
        except asyncio.CancelledError:
            print("Ingestion cancelled.")
            self.update_state(type="cancelled")
            await self.emit_state()
        except Exception as e:
            print(f"CRITICAL ERROR in ingestion loop: {e}")
            self.update_state(type="error", message=str(e))
            await self.emit_state()
        finally:
            self.executor = None

# Global Instance
ingestion_app_service = IngestionAppService()
