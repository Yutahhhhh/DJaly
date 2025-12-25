from typing import List, Optional, Dict
from sqlmodel import Session, select, func
from domain.models.track import Track

class GenreRepository:
    def __init__(self, session: Session):
        self.session = session

    def get_unknown_tracks(self, offset: int = 0, limit: int = 50, mode: str = "genre") -> List[Track]:
        query = select(Track)
        if mode == "subgenre":
            # Subgenre is unknown if it's empty or null
            query = query.where((Track.subgenre == None) | (Track.subgenre == ""))
        else:
            # Genre is unknown if not verified
            query = query.where(Track.is_genre_verified == False)
            
        statement = query.offset(offset).limit(limit)
        return self.session.exec(statement).all()

    def get_all_unknown_track_ids(self, mode: str = "genre") -> List[int]:
        query = select(Track.id)
        if mode == "subgenre":
            query = query.where((Track.subgenre == None) | (Track.subgenre == ""))
        else:
            query = query.where(Track.is_genre_verified == False)
            
        return self.session.exec(query).all()

    def get_tracks_by_ids(self, track_ids: List[int]) -> List[Track]:
        statement = select(Track).where(Track.id.in_(track_ids))
        return self.session.exec(statement).all()

    def get_all_tracks_with_genre(self) -> List[Track]:
        statement = select(Track).where(Track.genre != None).where(Track.genre != "Unknown")
        return self.session.exec(statement).all()

    def get_all_genres(self) -> List[str]:
        """Get all unique genres"""
        stmt = select(Track.genre).where(
            Track.genre != None,
            Track.genre != "",
            Track.genre != "Unknown"
        ).distinct()
        genres = self.session.exec(stmt).all()
        return sorted([g for g in genres if g])

    def get_all_subgenres(self) -> List[str]:
        """Get all unique subgenres"""
        stmt = select(Track.subgenre).where(
            Track.subgenre != None,
            Track.subgenre != ""
        ).distinct()
        subgenres = self.session.exec(stmt).all()
        return sorted([s for s in subgenres if s])

    def get_all_tracks_with_genre_any(self) -> List[Track]:
        statement = select(Track).where(Track.genre != None)
        return self.session.exec(statement).all()
