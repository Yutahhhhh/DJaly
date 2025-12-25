import asyncio
from typing import List, Dict, Any, Optional
from fastapi import WebSocket
from sqlmodel import Session, select, or_, func
from infra.database.connection import engine
from models import Track, Lyrics
from utils.external_metadata import fetch_itunes_release_date, fetch_lrclib_lyrics
from datetime import datetime
from app.services.background_task_service import BackgroundTaskService

class MetadataAppService(BackgroundTaskService):
    def __init__(self):
        super().__init__()
        self.state.update({
            "updated": 0,
            "current_track": "",
            "update_type": None
        })

    async def start_update(self, update_type: str, overwrite: bool, track_ids: Optional[List[int]] = None) -> bool:
        return await self.start_task(self._run_update(update_type, overwrite, track_ids))

    async def cancel_update(self):
        await self.cancel_task()

    async def _run_update(self, update_type: str, overwrite: bool, track_ids: Optional[List[int]] = None):
        print(f"DEBUG: _run_update started", flush=True)
        
        # Reset custom state
        self.update_state(updated=0, current_track="", update_type=update_type)
        
        try:
            with Session(engine) as session:
                query = select(Track)
                
                # Apply ID filter if provided
                if track_ids is not None:
                    query = query.where(Track.id.in_(track_ids))
                
                # If not overwriting, filter out tracks that already have data
                if not overwrite:
                    if update_type == "release_date":
                        # Skip tracks that already have a year
                        query = query.where(or_(Track.year.is_(None), Track.year == 0))
                    elif update_type == "lyrics":
                        # Skip tracks that already have lyrics
                        # Note: Need to join Lyrics table or use exists
                        # Simple approach: Left join and check for null or empty
                        query = query.outerjoin(Lyrics, Track.id == Lyrics.track_id)
                        query = query.where(or_(Lyrics.track_id.is_(None), func.length(func.trim(Lyrics.content)) == 0))

                tracks = session.exec(query).all()
                
                total = len(tracks)
                print(f"DEBUG: Found {total} tracks to process (Overwrite: {overwrite})", flush=True)
                
                self.update_state(
                    type="start",
                    total=total,
                    message=f"Starting {update_type} update..."
                )
                await self.emit_state()

                for i, track in enumerate(tracks):
                    if not self.is_running:
                        break

                    self.update_state(
                        current=i + 1,
                        current_track=f"{track.artist} - {track.title}",
                        type="processing"
                    )
                    await self.emit_state()

                    try:
                        updated = False
                        if update_type == "release_date":
                            updated = await self._update_release_date(session, track, overwrite)
                        elif update_type == "lyrics":
                            updated = await self._update_lyrics(session, track, overwrite)
                        
                        if updated:
                            self.state["updated"] += 1
                        else:
                            self.state["skipped"] += 1
                            
                    except Exception as e:
                        print(f"Error updating {track.id}: {e}")
                        self.state["errors"] += 1
                    
                    self.state["processed"] += 1
                    
                    # Rate limiting / nice to API
                    # Only sleep if we actually attempted an update (which we assume we did if we are here, 
                    # because we filtered out the ones we would skip)
                    # iTunes: ~20 req/min -> 3.0s
                    # LRCLIB: More permissive, but be nice -> 1.0s
                    sleep_time = 3.0 if update_type == "release_date" else 1.0
                    await asyncio.sleep(sleep_time) 

            self.update_state(type="complete", message="Update complete")
            await self.emit_state()

        except Exception as e:
            print(f"Metadata update error: {e}")
            self.update_state(type="error", message=str(e))
            await self.emit_state()
        finally:
            self.is_running = False

    async def _update_release_date(self, session: Session, track: Track, overwrite: bool) -> bool:
        if track.year and not overwrite:
            # print(f"DEBUG: Skipping {track.artist} - {track.title} (Year exists: {track.year})")
            return False
        
        print(f"DEBUG: Fetching release date for {track.artist} - {track.title}")
        release_date = await fetch_itunes_release_date(track.artist, track.title)
        if release_date:
            # release_date is "YYYY-MM-DDTHH:MM:SSZ"
            try:
                year = int(release_date[:4])
                if track.year != year:
                    track.year = year
                    session.add(track)
                    session.commit()
                    return True
            except:
                pass
        return False

    async def _update_lyrics(self, session: Session, track: Track, overwrite: bool) -> bool:
        lyrics = session.get(Lyrics, track.id)
        if lyrics and lyrics.content and not overwrite:
            return False
        
        data = await fetch_lrclib_lyrics(track.artist, track.title, track.album, track.duration)
        if data:
            # Prefer synced lyrics, then plain
            content = data.get("syncedLyrics") or data.get("plainLyrics")
            if content:
                if not lyrics:
                    lyrics = Lyrics(track_id=track.id)
                    session.add(lyrics)
                
                lyrics.content = content
                lyrics.source = "lrclib"
                lyrics.updated_at = datetime.now()
                session.add(lyrics)
                session.commit()
                return True
        return False

metadata_app_service = MetadataAppService()
