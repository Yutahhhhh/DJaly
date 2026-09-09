from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field


class MirrorPlaylist(BaseModel):
    external_id: str
    parent_external_id: Optional[str] = None
    name: str
    order: int = 0
    kind: Literal["folder", "playlist", "smart"] = "playlist"


class MirrorMember(BaseModel):
    playlist_external_id: str
    position: int = 0
    external_track_id: Optional[str] = None
    local_track_id: Optional[int] = None
    filepath: Optional[str] = None
    title: Optional[str] = None
    artist: Optional[str] = None
    bpm: Optional[float] = None
    key: Optional[str] = None
    duration: Optional[float] = None


class MirrorImport(BaseModel):
    source_id: str = Field(min_length=1, max_length=200)
    source_name: str = Field(min_length=1, max_length=300)
    playlists: list[MirrorPlaylist]
    members: list[MirrorMember] = []


class LocalPlaylistCreate(BaseModel):
    name: str = Field(min_length=1, max_length=300)


class LocalPlaylistRename(BaseModel):
    name: str = Field(min_length=1, max_length=300)


class LocalPlaylistTrackAdd(BaseModel):
    track_id: int
    position: Optional[int] = Field(default=None, ge=0)


class MirrorPlaylistCopy(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=300)


class PlaySessionCreate(BaseModel):
    id: str = Field(min_length=1, max_length=200)
    deck_count: Literal[2, 4] = 2


class HistoryUpsert(BaseModel):
    event_key: str = Field(min_length=1, max_length=300)
    session_id: str
    deck: Literal["A", "B", "C", "D"]
    track_id: int
    loaded_at: Optional[datetime] = None
    first_played_at: Optional[datetime] = None
    ended_at: Optional[datetime] = None
    played_ms: int = Field(default=0, ge=0)
    completed: bool = False
    reason: Optional[str] = None


class RecordingName(BaseModel):
    """保存時に付ける名前。ミックス名は必須、アーティスト名は任意。"""

    artist: str = Field(default="", max_length=200)
    title: str = Field(min_length=1, max_length=200)
    # Omitted by older clients: keep the recorder's original format.
    format: Optional[Literal["wav", "flac", "mp3"]] = None


class RecordingUpsert(BaseModel):
    recording_key: str = Field(min_length=1, max_length=300)
    session_id: Optional[str] = None
    filepath: str
    started_at: datetime
    ended_at: Optional[datetime] = None
    duration_ms: int = Field(default=0, ge=0)
    status: Literal["recording", "completed", "failed"] = "recording"
    error: Optional[str] = None
