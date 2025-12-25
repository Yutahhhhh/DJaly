from typing import List, Optional, Dict, Any
from sqlmodel import Session, select, desc
from datetime import datetime

from domain.models.setlist import Setlist, SetlistTrack
from domain.models.track import Track
from domain.models.lyrics import Lyrics

class SetlistRepository:
    def __init__(self, session: Session):
        self.session = session

    def find_all(self) -> List[Setlist]:
        return self.session.exec(select(Setlist).order_by(desc(Setlist.updated_at))).all()

    def get_by_id(self, setlist_id: int) -> Optional[Setlist]:
        return self.session.get(Setlist, setlist_id)

    def create(self, setlist: Setlist) -> Setlist:
        self.session.add(setlist)
        self.session.commit()
        self.session.refresh(setlist)
        return setlist

    def update(self, setlist: Setlist) -> Setlist:
        setlist.updated_at = datetime.now()
        self.session.add(setlist)
        self.session.commit()
        self.session.refresh(setlist)
        return setlist

    def delete(self, setlist: Setlist):
        self.session.delete(setlist)
        self.session.commit()

    def get_tracks(self, setlist_id: int) -> List[tuple[SetlistTrack, Track, Optional[str]]]:
        query = (
            select(SetlistTrack, Track, Lyrics.content)
            .where(SetlistTrack.setlist_id == setlist_id)
            .where(SetlistTrack.track_id == Track.id)
            .outerjoin(Lyrics, Track.id == Lyrics.track_id)
            .order_by(SetlistTrack.position)
        )
        return self.session.exec(query).all()

    def clear_tracks(self, setlist_id: int):
        existing = self.session.exec(select(SetlistTrack).where(SetlistTrack.setlist_id == setlist_id)).all()
        for e in existing:
            self.session.delete(e)
        # Commit is expected to be handled by the caller or subsequent operations if part of a transaction, 
        # but here we commit to ensure state.
        # In a stricter unit of work pattern, we might defer commit.
        # For now, matching existing behavior.
        self.session.commit()

    def add_track(self, setlist_track: SetlistTrack):
        self.session.add(setlist_track)
        # Batch addition usually happens, so we might not commit every single add if called in loop.
        # But for simplicity in repository, we can just add. 
        # The service will commit.
