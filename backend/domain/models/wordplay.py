from datetime import datetime
from typing import Optional

from sqlalchemy import UniqueConstraint
from sqlmodel import Field, SQLModel


class WordplayPair(SQLModel, table=True):
    """A directional, version-specific wordplay transition between two tracks."""

    __tablename__ = "wordplay_pairs"
    __table_args__ = (
        UniqueConstraint(
            "from_track_id",
            "to_track_id",
            "normalized_keyword",
            name="uq_wordplay_pair_direction_keyword",
        ),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    from_track_id: int = Field(index=True)
    to_track_id: int = Field(index=True)
    keyword: str
    normalized_keyword: str
    source_phrase: str
    target_phrase: str
    source_section_position: str = "unknown"
    target_section_position: str = "unknown"
    source_cue_mode: str = "section_end"
    from_timestamp: Optional[float] = None
    source_cue_end_timestamp: Optional[float] = None
    to_timestamp: Optional[float] = None
    target_intro_timestamp: Optional[float] = None
    target_landing_timestamp: Optional[float] = None
    transition_notes: str = ""
    source_url: str = ""
    evidence_type: str = "hypothesis"
    verification_status: str = "unverified"
    status: str = Field(default="pending", index=True)
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
