from datetime import datetime

from collections.abc import Sequence

from sqlmodel import Session, col, select

from domain.models.performance_metadata import TrackPerformanceMetadata


class PerformanceMetadataRepository:
    def __init__(self, session: Session):
        self.session = session

    def get(self, track_id: int) -> TrackPerformanceMetadata | None:
        return self.session.get(TrackPerformanceMetadata, track_id)

    def get_many(self, track_ids: Sequence[int]) -> list[TrackPerformanceMetadata]:
        """Rows for the given tracks. Missing tracks are simply absent."""
        if not track_ids:
            return []
        statement = select(TrackPerformanceMetadata).where(
            col(TrackPerformanceMetadata.track_id).in_(list(track_ids))
        )
        return list(self.session.exec(statement).all())

    def save(
        self,
        metadata: TrackPerformanceMetadata,
        *,
        commit: bool = True,
    ) -> TrackPerformanceMetadata:
        metadata.updated_at = datetime.now()
        self.session.add(metadata)
        if commit:
            self.session.commit()
            self.session.refresh(metadata)
        return metadata
