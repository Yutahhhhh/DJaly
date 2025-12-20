from typing import List, Optional
from sqlmodel import Session, select
from domain.models.track import Track

class GenreRepository:
    def __init__(self, session: Session):
        self.session = session

    def get_unknown_tracks(self, offset: int = 0, limit: int = 50) -> List[Track]:
        statement = select(Track).where(Track.is_genre_verified == False).offset(offset).limit(limit)
        return self.session.exec(statement).all()

    def get_all_unknown_track_ids(self) -> List[int]:
        statement = select(Track.id).where(Track.is_genre_verified == False)
        return self.session.exec(statement).all()

    def get_tracks_by_ids(self, track_ids: List[int]) -> List[Track]:
        statement = select(Track).where(Track.id.in_(track_ids))
        return self.session.exec(statement).all()

    def get_all_tracks_with_genre(self) -> List[Track]:
        statement = select(Track).where(Track.genre != None).where(Track.genre != "Unknown")
        return self.session.exec(statement).all()

    def get_all_unique_genres(self) -> List[str]:
        statement = select(Track.genre).where(Track.genre != None).distinct()
        genres = self.session.exec(statement).all()
        return sorted([g for g in genres if g])

    def get_all_tracks_with_genre_any(self) -> List[Track]:
        statement = select(Track).where(Track.genre != None)
        return self.session.exec(statement).all()
