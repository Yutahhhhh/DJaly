import asyncio
from typing import List
from sqlmodel import Session
from infra.database.connection import engine
from app.services.background_task_service import BackgroundTaskService
from app.services.genre_app_service import GenreAppService
from api.schemas.genres import AnalysisMode

class GenreBackgroundService(BackgroundTaskService):
    def __init__(self):
        super().__init__()
        self.state.update({
            "updated": 0,
            "current_track": "",
            "mode": None
        })

    async def start_batch_analysis(self, track_ids: List[int], overwrite: bool, mode: AnalysisMode) -> bool:
        return await self.start_task(self._run_batch_analysis(track_ids, overwrite, mode))

    async def cancel_analysis(self):
        await self.cancel_task()

    async def _run_batch_analysis(self, track_ids: List[int], overwrite: bool, mode: AnalysisMode):
        self.update_state(updated=0, current_track="", mode=mode.value)
        
        try:
            total = len(track_ids)
            self.update_state(
                type="start",
                total=total,
                message=f"Starting batch analysis for {total} tracks..."
            )
            await self.emit_state()

            # We need to process one by one or in small chunks to manage session and LLM rate limits
            # GenreAppService uses generate_text which calls Ollama. Ollama might be slow.
            # We should probably do it sequentially or with a small semaphore if Ollama supports concurrency.
            # For now, sequential is safer.

            for i, track_id in enumerate(track_ids):
                if not self.is_running:
                    break

                # Create a new session for each track or small batch to avoid long-lived sessions
                with Session(engine) as session:
                    service = GenreAppService(session)
                    track = service.track_repository.get_by_id(track_id)
                    
                    track_title = f"{track.artist} - {track.title}" if track else f"Track {track_id}"
                    
                    self.update_state(
                        current=i + 1,
                        current_track=track_title,
                        type="processing"
                    )
                    await self.emit_state()

                    try:
                        # This is synchronous in GenreAppService, but that's fine since we are in a thread/async loop
                        # Wait, if it's synchronous and CPU bound or blocking IO, it will block the loop.
                        # generate_text uses requests (blocking).
                        # We should run it in an executor if it blocks.
                        # But for now, let's assume it's "fast enough" or we accept blocking the loop slightly 
                        # (since we are the only task running on this service instance).
                        # Actually, blocking the loop prevents WebSocket heartbeats/broadcasts.
                        # So we MUST run blocking code in executor.
                        
                        # However, GenreAppService is complex.
                        # Let's wrap the call in to_thread.
                        
                        await asyncio.to_thread(
                            service.analyze_track_with_llm, 
                            track_id=track_id, 
                            overwrite=overwrite, 
                            mode=mode
                        )
                        
                        self.state["updated"] += 1
                        self.state["processed"] += 1
                        
                    except Exception as e:
                        print(f"Error analyzing track {track_id}: {e}")
                        self.state["errors"] += 1
                        self.state["processed"] += 1 # Count as processed even if error
                
                # Small delay to yield control
                await asyncio.sleep(0.1)

            self.update_state(type="complete", message="Batch analysis complete")
            await self.emit_state()

        except Exception as e:
            print(f"Batch analysis error: {e}")
            self.update_state(type="error", message=str(e))
            await self.emit_state()

genre_background_service = GenreBackgroundService()
