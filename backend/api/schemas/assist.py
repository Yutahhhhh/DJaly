from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class DeckObservationIn(BaseModel):
    """One deck exactly as the desktop client read it from rekordbox's UI.

    These are observations, not assertions: every field may be missing, and the
    server never treats them as an identity on their own.
    """

    model_config = ConfigDict(extra="forbid")

    slot: int = Field(ge=1, le=4)
    loaded: bool = False
    title: Optional[str] = Field(default=None, max_length=512)
    artist: Optional[str] = Field(default=None, max_length=512)
    track_bpm: Optional[float] = None
    tempo_bpm: Optional[float] = None
    display_key: Optional[str] = Field(default=None, max_length=32)


class DeckResolveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decks: List[DeckObservationIn] = Field(default_factory=list, max_length=4)
    # Audio files the rekordbox process has open. Includes sampler and metronome
    # files, so this is a candidate set the server narrows down, not deck state.
    open_audio_paths: List[str] = Field(default_factory=list, max_length=256)


class AssistRecommendRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_track_id: int
    intent: Literal["groove", "shift", "wordplay"] = "groove"
    energy_direction: Literal["up", "hold", "down"] = "hold"
    limit: int = Field(default=12, ge=1, le=50)
    exclude_track_ids: List[int] = Field(default_factory=list, max_length=10000)
    genre_scope: Literal["any", "same_genre", "same_subgenre"] = "any"
    genres: Optional[List[str]] = Field(default=None, max_length=32)


__all__ = ["AssistRecommendRequest", "DeckObservationIn", "DeckResolveRequest"]
