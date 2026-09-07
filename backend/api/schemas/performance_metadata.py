import math
from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StrictFloat, StrictInt, field_validator, model_validator


FiniteNumber = Annotated[StrictInt | StrictFloat, Field(ge=0)]


class CuePoint(BaseModel):
    model_config = ConfigDict(extra="forbid")

    slot: StrictInt = Field(ge=0, le=7)
    position_ms: FiniteNumber
    label: str = Field(default="", max_length=100)
    color: str | None = Field(default=None, max_length=32)

    @field_validator("position_ms")
    @classmethod
    def finite_position(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("must be finite")
        return value


class SavedLoop(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=64)
    start_ms: FiniteNumber
    end_ms: FiniteNumber
    label: str = Field(default="", max_length=100)

    @field_validator("id")
    @classmethod
    def nonblank_id(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return value

    @field_validator("start_ms", "end_ms")
    @classmethod
    def finite_position(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("must be finite")
        return value

    @model_validator(mode="after")
    def ordered(self) -> "SavedLoop":
        if self.end_ms <= self.start_ms:
            raise ValueError("end_ms must be greater than start_ms")
        return self


class BeatGrid(BaseModel):
    model_config = ConfigDict(extra="forbid")

    bpm: StrictInt | StrictFloat = Field(ge=20, le=300)
    first_beat_ms: FiniteNumber
    beats_per_bar: StrictInt = Field(default=4, ge=1, le=16)

    @field_validator("bpm", "first_beat_ms")
    @classmethod
    def finite_number(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("must be finite")
        return value


class PerformanceMetadataWrite(BaseModel):
    """Complete replacement payload. Revision 0 creates the initial record."""

    model_config = ConfigDict(extra="forbid")

    revision: StrictInt = Field(ge=0)
    cue_points: list[CuePoint] = Field(default_factory=list, max_length=8)
    loops: list[SavedLoop] = Field(default_factory=list, max_length=32)
    beat_grid: BeatGrid | None = None

    @model_validator(mode="after")
    def unique_keys(self) -> "PerformanceMetadataWrite":
        slots = [cue.slot for cue in self.cue_points]
        if len(slots) != len(set(slots)):
            raise ValueError("cue point slots must be unique")
        loop_ids = [loop.id for loop in self.loops]
        if len(loop_ids) != len(set(loop_ids)):
            raise ValueError("loop ids must be unique")
        return self


class PerformanceMetadataRead(BaseModel):
    track_id: int
    revision: int
    cue_points: list[CuePoint]
    loops: list[SavedLoop]
    beat_grid: BeatGrid | None
    created_at: datetime | None
    updated_at: datetime | None
