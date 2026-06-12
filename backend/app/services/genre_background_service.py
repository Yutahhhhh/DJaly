import asyncio
from typing import List
from sqlmodel import Session
from infra.database.connection import engine
from app.services.background_task_service import BackgroundTaskService
from app.services.genre_app_service import GenreAppService
from api.schemas.genres import AnalysisMode
from utils.logger import get_logger

logger = get_logger(__name__)

# 1回の LLM コールで解析する曲数 (コール数削減 + チャンク内のラベル一貫性向上)
BATCH_CHUNK_SIZE = 15
# 結果ログとして保持する直近件数
RECENT_RESULTS_LIMIT = 50

class GenreBackgroundService(BackgroundTaskService):
    def __init__(self):
        super().__init__()
        self.state.update({
            "updated": 0,
            "current_track": "",
            "mode": None,
            "recent_results": [],
            "failed_track_ids": []
        })

    async def start_batch_analysis(self, track_ids: List[int], overwrite: bool, mode: AnalysisMode) -> bool:
        return await self.start_task(self._run_batch_analysis(track_ids, overwrite, mode))

    async def cancel_analysis(self):
        await self.cancel_task()

    async def _run_batch_analysis(self, track_ids: List[int], overwrite: bool, mode: AnalysisMode):
        self.update_state(
            updated=0,
            current_track="",
            mode=mode.value,
            recent_results=[],
            failed_track_ids=[]
        )

        try:
            total = len(track_ids)
            self.update_state(
                type="start",
                total=total,
                message=f"Starting batch analysis for {total} tracks..."
            )
            await self.emit_state()

            # チャンク単位で analyze_tracks_batch_with_llm を使用する。
            # 1曲ごとに LLM を呼ぶより大幅に高速・低コストで、
            # 同一チャンク内のジャンルラベルの一貫性も上がる。
            for chunk_start in range(0, total, BATCH_CHUNK_SIZE):
                if not self.is_running:
                    break

                chunk = track_ids[chunk_start:chunk_start + BATCH_CHUNK_SIZE]

                with Session(engine) as session:
                    service = GenreAppService(session)

                    # 進捗表示用に先頭曲のタイトルを取得
                    first_track = service.track_repository.get_by_id(chunk[0])
                    chunk_label = (
                        f"{first_track.artist} - {first_track.title}" if first_track else f"Track {chunk[0]}"
                    )
                    self.update_state(
                        current=min(chunk_start + len(chunk), total),
                        current_track=f"{chunk_label} (+{len(chunk) - 1} more)" if len(chunk) > 1 else chunk_label,
                        type="processing"
                    )
                    await self.emit_state()

                    try:
                        # LLM 呼び出しはブロッキング I/O のためスレッドへ逃がす
                        results = await asyncio.to_thread(
                            service.analyze_tracks_batch_with_llm,
                            chunk,
                            mode,
                            overwrite
                        )

                        self.state["updated"] += len(results)
                        self.state["processed"] += len(chunk)

                        # 直近の変更ログを保持 (フロントでのライブ表示用)
                        for r in results:
                            self.state["recent_results"].append({
                                "track_id": r.track_id,
                                "title": r.title,
                                "artist": r.artist,
                                "old_genre": r.old_genre,
                                "new_genre": r.new_genre
                            })
                        self.state["recent_results"] = self.state["recent_results"][-RECENT_RESULTS_LIMIT:]

                    except Exception as e:
                        logger.error(f"Error analyzing chunk starting at track {chunk[0]}: {e}")
                        self.state["errors"] += len(chunk)
                        self.state["processed"] += len(chunk)
                        self.state["failed_track_ids"].extend(chunk)

                await self.emit_state()
                # Small delay to yield control
                await asyncio.sleep(0.1)

            self.update_state(type="complete", message="Batch analysis complete")
            await self.emit_state()

        except Exception as e:
            logger.error(f"Batch analysis error: {e}")
            self.update_state(type="error", message=str(e))
            await self.emit_state()

genre_background_service = GenreBackgroundService()
