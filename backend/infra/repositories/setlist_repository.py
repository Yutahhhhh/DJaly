from typing import List, Optional, Dict, Any
from sqlmodel import Session, select, desc, text
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

    def clear_tracks(self, setlist_id: int, commit: bool = True):
        # Keep deletion bounded in Python even for very large playlists.
        self.session.exec(text("DELETE FROM setlist_tracks WHERE setlist_id=:id"), params={"id": setlist_id})
        if commit:
            self.session.commit()

    def add_track(self, setlist_track: SetlistTrack):
        self.session.add(setlist_track)
        # Batch addition usually happens, so we might not commit every single add if called in loop.
        # But for simplicity in repository, we can just add. 
        # The service will commit.

    def find_page(self, limit: int, offset: int) -> Dict[str, Any]:
        total = int(self.session.exec(text("SELECT count(*) FROM setlists")).one()[0])
        rows = self.session.exec(text("""
            SELECT s.*, 'djaly' AS source, true AS editable,
                   (SELECT count(*) FROM setlist_tracks st JOIN tracks t ON t.id=st.track_id
                    WHERE st.setlist_id=s.id) AS track_count
            FROM setlists s ORDER BY s.updated_at DESC, s.id DESC
            LIMIT :limit OFFSET :offset
        """), params={"limit": limit, "offset": offset}).all()
        items = [dict(row._mapping) for row in rows]
        return {"items": items, "total": total, "limit": limit, "offset": offset,
                "has_more": offset + len(items) < total}

    def get_tracks_page(self, setlist_id: int, limit: int, offset: int) -> Dict[str, Any]:
        total = int(self.session.exec(text(
            """SELECT count(*) FROM setlist_tracks st JOIN tracks t ON t.id=st.track_id
               WHERE st.setlist_id=:id"""
        ), params={"id": setlist_id}).one()[0])
        rows = self.session.exec(text("""
            SELECT t.*, st.id AS setlist_track_id, st.position, st.transition_note,
                   st.wordplay_json,
                   (l.content IS NOT NULL AND length(trim(l.content)) > 0) AS has_lyrics
            FROM setlist_tracks st JOIN tracks t ON t.id=st.track_id
            LEFT JOIN lyrics l ON l.track_id=t.id
            WHERE st.setlist_id=:id ORDER BY st.position, st.id
            LIMIT :limit OFFSET :offset
        """), params={"id": setlist_id, "limit": limit, "offset": offset}).all()
        items = [dict(row._mapping) for row in rows]
        return {"items": items, "total": total, "limit": limit, "offset": offset,
                "has_more": offset + len(items) < total}

    def insert_track(self, setlist_id: int, track_id: int, position: Optional[int]) -> int:
        count = int(self.session.exec(text(
            "SELECT count(*) FROM setlist_tracks WHERE setlist_id=:id"
        ), params={"id": setlist_id}).one()[0])
        target = count if position is None else min(position, count)
        self.session.exec(text("""
            UPDATE setlist_tracks SET position=position+1
            WHERE setlist_id=:id AND position>=:position
        """), params={"id": setlist_id, "position": target})
        row = self.session.exec(text("""
            INSERT INTO setlist_tracks (setlist_id,track_id,position)
            VALUES (:setlist_id,:track_id,:position) RETURNING id
        """), params={"setlist_id": setlist_id, "track_id": track_id, "position": target}).one()
        self.session.exec(text("UPDATE setlists SET updated_at=CURRENT_TIMESTAMP WHERE id=:id"), params={"id": setlist_id})
        self.session.commit()
        return int(row[0])

    def remove_track_entry(self, setlist_id: int, entry_id: int) -> bool:
        row = self.session.exec(text("""
            DELETE FROM setlist_tracks WHERE setlist_id=:setlist_id AND id=:entry_id
            RETURNING position
        """), params={"setlist_id": setlist_id, "entry_id": entry_id}).first()
        if row is None:
            self.session.rollback()
            return False
        position = int(row[0])
        self.session.exec(text("""
            UPDATE setlist_tracks SET position=position-1
            WHERE setlist_id=:id AND position>:position
        """), params={"id": setlist_id, "position": position})
        self.session.exec(text("UPDATE setlists SET updated_at=CURRENT_TIMESTAMP WHERE id=:id"), params={"id": setlist_id})
        self.session.commit()
        return True
