from datetime import datetime

from sqlmodel import Field, SQLModel


class TrackPerformanceMetadata(SQLModel, table=True):
    """DJ metadata owned by Djaly, independent of the transient engine state."""

    __tablename__ = "track_performance_metadata"

    track_id: int = Field(primary_key=True)
    cue_points_json: str = "[]"
    loops_json: str = "[]"
    beat_grid_json: str | None = None
    revision: int = 1
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
