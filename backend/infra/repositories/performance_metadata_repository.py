from datetime import datetime

from sqlmodel import Session

from domain.models.performance_metadata import TrackPerformanceMetadata


class PerformanceMetadataRepository:
    def __init__(self, session: Session):
        self.session = session

    def get(self, track_id: int) -> TrackPerformanceMetadata | None:
        return self.session.get(TrackPerformanceMetadata, track_id)

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
