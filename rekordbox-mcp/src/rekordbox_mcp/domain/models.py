"""Pydantic models for the Rekordbox MCP domain."""

from __future__ import annotations

import csv
from datetime import datetime
from enum import IntEnum, StrEnum
from pathlib import Path
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, field_validator


class CueType(IntEnum):
    """Cue point types matching rekordbox database values."""

    MEMORY = 0
    HOT_CUE_1 = 1
    HOT_CUE_2 = 2
    HOT_CUE_3 = 3
    HOT_CUE_4 = 4
    HOT_CUE_5 = 5
    HOT_CUE_6 = 6
    HOT_CUE_7 = 7
    HOT_CUE_8 = 8
    HOT_CUE_9 = 9


class CueKind(IntEnum):
    """Cue kind values from rekordbox (matches CUE_SYSTEM)."""

    FIRST_BEAT = 1
    LOOP_IN = 2
    VOCAL_BUILDUP = 3
    DROP = 5
    BREAKDOWN = 6
    SPECIAL = 7
    OUTRO = 8
    LOOP_OUT = 9


class HotCueColorTableIndex(IntEnum):
    """Hot cue color table indices from rekordbox."""

    RED = 42
    ORANGE = 56
    YELLOW = 32
    GREEN = 18
    CYAN = 9
    BLUE = 1
    PURPLE = 27
    PINK = 41
    WHITE = 0


class MemoryCueColor(IntEnum):
    """Memory cue colors (0-7)."""

    RED = 1
    ORANGE = 2
    YELLOW = 3
    GREEN = 4
    CYAN = 5
    BLUE = 6
    PURPLE = 7
    NONE = 0


class PhraseLabel(StrEnum):
    """PSSI phrase labels."""

    INTRO = "Intro"
    UP = "Up"
    DOWN = "Down"
    CHORUS = "Chorus"
    VERSE1 = "Verse1"
    VERSE2 = "Verse2"
    VERSE3 = "Verse3"
    VERSE4 = "Verse4"
    VERSE5 = "Verse5"
    VERSE6 = "Verse6"
    BRIDGE = "Bridge"
    OUTRO = "Outro"
    UNKNOWN = "Unknown"


class Mood(IntEnum):
    """PSSI mood values."""

    HIGH = 1
    MID = 2
    LOW = 3


class OperationMode(StrEnum):
    """Operation modes."""

    READONLY = "readonly"
    XML = "xml"
    MASTERDB = "masterdb"


class ChangeAction(StrEnum):
    """ChangeSet actions."""

    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"
    REPLACE = "replace"
    MERGE = "merge"


class BackupType(StrEnum):
    """Backup types."""

    FULL = "full"
    DIFFERENTIAL = "differential"
    PROTECTED = "protected"


class CueSlotConfig(BaseModel):
    """Configuration for a single cue slot (from cue-system.csv)."""

    pad: str = Field(description="Pad letter A-H")
    kind: int = Field(description="DB Kind value (1,2,3,5,6,7,8,9)")
    hot_cue_label: str = Field(description="Hot cue label")
    memory_cue_label: str = Field(description="Memory cue label")
    hot_cue_color_table_index: int = Field(description="Hot cue ColorTableIndex")
    hot_cue_color: int = Field(description="Hot cue Color (-1 for table index)")
    memory_cue_color_table_index: int | None = Field(
        default=None, description="Memory cue ColorTableIndex"
    )
    memory_cue_color: int = Field(description="Memory cue Color (0-7)")
    is_loop: bool = Field(description="Whether this slot is a loop")
    memory_offset_bars: int = Field(description="Memory cue offset in bars (0 or 16)")

    @property
    def hot_cue_num(self) -> int:
        """Get hot cue number (1-9) from kind."""
        kind_to_num = {
            1: 1,
            2: 2,
            3: 3,
            5: 4,
            6: 5,
            7: 6,
            8: 7,
            9: 8,
        }
        return kind_to_num.get(self.kind, 0)


class CueProfile(BaseModel):
    """Cue profile containing 8 hot cue + 8 memory cue slots."""

    name: str = Field(description="Profile name")
    slots: list[CueSlotConfig] = Field(description="Cue slot configurations (8 slots)")

    @classmethod
    def from_csv(cls, path: str | Path) -> CueProfile:
        """Load a djcues-compatible ``cue-system.csv`` profile.

        The first five columns are positional because the format contains two
        columns named ``Label``.  An optional ``memory_offset_bars`` column is
        accepted (header matching is case-insensitive and ignores spaces and
        underscores).
        """
        csv_path = Path(path).expanduser()
        with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.reader(handle))
        if not rows:
            raise ValueError(f"Cue profile CSV is empty: {csv_path}")

        header = [cell.strip() for cell in rows[0]]
        normalize = lambda value: "".join(value.lower().split()).replace("_", "")
        offset_index = next(
            (i for i, value in enumerate(header) if normalize(value) in {"memoryoffsetbars", "offsetbars"}),
            None,
        )
        kind_by_pad = {pad: kind for pad, kind in zip("ABCDEFGH", (1, 2, 3, 5, 6, 7, 8, 9))}
        colors = {
            "green": (HotCueColorTableIndex.GREEN, MemoryCueColor.GREEN),
            "red": (HotCueColorTableIndex.RED, MemoryCueColor.RED),
            "blue": (HotCueColorTableIndex.BLUE, MemoryCueColor.BLUE),
            "yellow": (HotCueColorTableIndex.YELLOW, MemoryCueColor.YELLOW),
            "cyan": (HotCueColorTableIndex.CYAN, MemoryCueColor.CYAN),
            "purple": (HotCueColorTableIndex.PURPLE, MemoryCueColor.PURPLE),
            "orange": (HotCueColorTableIndex.ORANGE, MemoryCueColor.ORANGE),
            "white": (HotCueColorTableIndex.WHITE, MemoryCueColor.NONE),
        }
        slots: list[CueSlotConfig] = []
        default_offsets = {"A": 0, "B": 0, "H": 0}
        for row in rows[1:]:
            if not row or not any(cell.strip() for cell in row):
                continue
            if len(row) < 5:
                raise ValueError(f"Invalid cue profile row in {csv_path}: expected 5 columns")
            pad = row[0].strip().upper()
            if pad not in kind_by_pad:
                raise ValueError(f"Invalid cue pad {pad!r} in {csv_path}")
            hot_color, memory_color = colors.get(row[2].strip().lower(), (HotCueColorTableIndex.WHITE, MemoryCueColor.NONE))
            offset = 0 if pad in default_offsets else 16
            if offset_index is not None and offset_index < len(row) and row[offset_index].strip():
                offset = int(row[offset_index].strip())
            slots.append(CueSlotConfig(
                pad=pad,
                kind=kind_by_pad[pad],
                hot_cue_label=row[1].strip(),
                memory_cue_label=row[4].strip(),
                hot_cue_color_table_index=int(hot_color),
                hot_cue_color=-1,
                memory_cue_color_table_index=None,
                memory_cue_color=int(memory_color),
                is_loop=pad in {"B", "H"},
                memory_offset_bars=offset,
            ))
        if not slots:
            raise ValueError(f"Cue profile CSV contains no slots: {csv_path}")
        return cls(name=csv_path.stem, slots=slots)

    @classmethod
    def default(cls) -> CueProfile:
        """Create the default cue profile matching cue-system.csv."""
        return cls(
            name="default",
            slots=[
                CueSlotConfig(
                    pad="A",
                    kind=1,
                    hot_cue_label="First Beat",
                    memory_cue_label="First Beat",
                    hot_cue_color_table_index=18,
                    hot_cue_color=-1,
                    memory_cue_color_table_index=None,
                    memory_cue_color=4,
                    is_loop=False,
                    memory_offset_bars=0,
                ),
                CueSlotConfig(
                    pad="B",
                    kind=2,
                    hot_cue_label="Loop In",
                    memory_cue_label="Loop In",
                    hot_cue_color_table_index=18,
                    hot_cue_color=255,
                    memory_cue_color_table_index=0,
                    memory_cue_color=4,
                    is_loop=True,
                    memory_offset_bars=0,
                ),
                CueSlotConfig(
                    pad="C",
                    kind=3,
                    hot_cue_label="Vocal / Buildup",
                    memory_cue_label="Buildup",
                    hot_cue_color_table_index=32,
                    hot_cue_color=-1,
                    memory_cue_color_table_index=None,
                    memory_cue_color=3,
                    is_loop=False,
                    memory_offset_bars=16,
                ),
                CueSlotConfig(
                    pad="D",
                    kind=5,
                    hot_cue_label="Drop",
                    memory_cue_label="Drop",
                    hot_cue_color_table_index=42,
                    hot_cue_color=-1,
                    memory_cue_color_table_index=None,
                    memory_cue_color=1,
                    is_loop=False,
                    memory_offset_bars=16,
                ),
                CueSlotConfig(
                    pad="E",
                    kind=6,
                    hot_cue_label="Breakdown",
                    memory_cue_label="Breakdown",
                    hot_cue_color_table_index=1,
                    hot_cue_color=-1,
                    memory_cue_color_table_index=None,
                    memory_cue_color=6,
                    is_loop=False,
                    memory_offset_bars=16,
                ),
                CueSlotConfig(
                    pad="F",
                    kind=7,
                    hot_cue_label="Special",
                    memory_cue_label="Special",
                    hot_cue_color_table_index=56,
                    hot_cue_color=-1,
                    memory_cue_color_table_index=None,
                    memory_cue_color=7,
                    is_loop=False,
                    memory_offset_bars=16,
                ),
                CueSlotConfig(
                    pad="G",
                    kind=8,
                    hot_cue_label="Outro",
                    memory_cue_label="Outro",
                    hot_cue_color_table_index=9,
                    hot_cue_color=-1,
                    memory_cue_color_table_index=None,
                    memory_cue_color=5,
                    is_loop=False,
                    memory_offset_bars=16,
                ),
                CueSlotConfig(
                    pad="H",
                    kind=9,
                    hot_cue_label="Loop Out",
                    memory_cue_label="Loop Out",
                    hot_cue_color_table_index=0,
                    hot_cue_color=255,
                    memory_cue_color_table_index=0,
                    memory_cue_color=2,
                    is_loop=True,
                    memory_offset_bars=0,
                ),
            ],
        )


class BeatGrid(BaseModel):
    """Beat grid timing derived from BPM and first beat position."""

    first_beat_ms: float = Field(description="First beat position in milliseconds")
    bpm: float = Field(description="BPM value (e.g., 128.0)")

    @property
    def ms_per_beat(self) -> float:
        return 60_000.0 / self.bpm

    def beat_to_ms(self, beat: int) -> float:
        """Convert 1-indexed beat number to milliseconds."""
        return self.first_beat_ms + (beat - 1) * self.ms_per_beat

    def ms_to_beat(self, ms: float) -> int:
        """Convert milliseconds to nearest 1-indexed beat number."""
        raw = (ms - self.first_beat_ms) / self.ms_per_beat + 1
        return max(1, round(raw))

    def bars_to_ms(self, bars: int) -> float:
        """Convert number of bars (4 beats each) to milliseconds."""
        return bars * 4 * self.ms_per_beat

    def snap_to_beat(self, ms: float) -> float:
        """Snap milliseconds to nearest beat."""
        beat = self.ms_to_beat(ms)
        return self.beat_to_ms(beat)

    def snap_to_bar(self, ms: float) -> float:
        """Snap milliseconds to nearest bar (downbeat)."""
        beat = self.ms_to_beat(ms)
        bar_beat = ((beat - 1) // 4) * 4 + 1
        return self.beat_to_ms(bar_beat)

    def get_bar_start_ms(self, bar: int) -> float:
        """Get millisecond position of bar start (1-indexed)."""
        beat = (bar - 1) * 4 + 1
        return self.beat_to_ms(beat)


class CuePoint(BaseModel):
    """A single cue point (hot cue, memory cue, or loop)."""

    id: str = Field(default_factory=lambda: str(uuid4()), description="Unique identifier")
    track_id: int = Field(description="Track ID")
    kind: int = Field(description="Cue kind (0=memory, 1-9=hot cue)")
    position_ms: float = Field(description="Position in milliseconds")
    loop_end_ms: float | None = Field(default=None, description="Loop end position in ms")
    color_table_index: int | None = Field(default=None, description="Hot cue ColorTableIndex")
    color: int = Field(default=0, description="Memory cue color (0-7)")
    comment: str = Field(default="", description="Cue comment/label")
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)

    @property
    def is_hot_cue(self) -> bool:
        return 1 <= self.kind <= 9

    @property
    def is_memory_cue(self) -> bool:
        return self.kind == 0

    @property
    def is_loop(self) -> bool:
        return self.loop_end_ms is not None

    @property
    def hot_cue_num(self) -> int | None:
        """Get hot cue number (1-8) from kind."""
        if not self.is_hot_cue:
            return None
        kind_to_num = {1: 1, 2: 2, 3: 3, 5: 4, 6: 5, 7: 6, 8: 7, 9: 8}
        return kind_to_num.get(self.kind)

    def to_db_dict(self) -> dict[str, Any]:
        """Convert to dictionary for database storage."""
        return {
            "ID": self.id,
            "ContentID": self.track_id,
            "Kind": self.kind,
            "InMsec": int(self.position_ms),
            "OutMsec": int(self.loop_end_ms) if self.loop_end_ms else 0,
            "ColorTableIndex": self.color_table_index or 0,
            "Color": self.color,
            "Comment": self.comment,
            "CreatedAt": self.created_at,
            "UpdatedAt": self.updated_at,
        }

    @classmethod
    def from_db_dict(cls, data: dict[str, Any]) -> CuePoint:
        """Create from database dictionary."""
        return cls(
            id=data.get("ID", str(uuid4())),
            track_id=data.get("ContentID", 0),
            kind=data.get("Kind", 0),
            position_ms=data.get("InMsec", 0),
            loop_end_ms=data.get("OutMsec") if data.get("OutMsec", 0) > 0 else None,
            color_table_index=data.get("ColorTableIndex") or None,
            color=data.get("Color", 0),
            comment=data.get("Comment", ""),
            created_at=data.get("CreatedAt", datetime.now()),
            updated_at=data.get("UpdatedAt", datetime.now()),
        )


class Phrase(BaseModel):
    """A phrase segment from PSSI analysis."""

    beat_start: int = Field(description="Start beat (1-indexed)")
    beat_end: int = Field(description="End beat (exclusive, start of next phrase)")
    kind: int = Field(description="Raw PSSI kind value")
    label: str = Field(description="Resolved label (Intro, Up, Down, Chorus, Outro, etc.)")
    position_ms: float = Field(description="Position in milliseconds")
    duration_ms: float = Field(description="Duration in milliseconds")
    mood: int = Field(default=2, description="PSSI mood (1=High, 2=Mid, 3=Low)")

    @property
    def beat_length(self) -> int:
        return self.beat_end - self.beat_start


class WaveformPoint(BaseModel):
    """A single point in the color waveform."""

    height: float = Field(description="Normalized amplitude 0.0-1.0")
    red: int = Field(description="Bass 0-7")
    green: int = Field(description="Mid 0-7")
    blue: int = Field(description="Treble 0-7")

    @property
    def rgb_hex(self) -> str:
        r = min(self.red, 7) * 255 // 7
        g = min(self.green, 7) * 255 // 7
        b = min(self.blue, 7) * 255 // 7
        return f"#{r:02x}{g:02x}{b:02x}"


class Track(BaseModel):
    """A rekordbox track with analysis data."""

    id: int = Field(description="Track ID")
    title: str = Field(description="Track title")
    artist: str = Field(description="Artist name")
    bpm: float = Field(description="BPM (e.g., 128.0)")
    duration_ms: float = Field(description="Duration in milliseconds")
    analysis_path: str = Field(description="Path to ANLZ analysis file")
    key: str | None = Field(default=None, description="Musical key (e.g., '5A')")
    genre: str | None = Field(default=None, description="Genre")
    cues: list[CuePoint] = Field(default_factory=list, description="Existing cue points")
    phrases: list[Phrase] = Field(default_factory=list, description="PSSI phrases")
    beat_grid: BeatGrid | None = Field(default=None, description="Beat grid")
    waveform: list[WaveformPoint] | None = Field(default=None, description="Color waveform")
    vocal_track: list[int] | None = Field(default=None, description="PVDI vocal confidence per frame (0-4)")

    @property
    def hot_cues(self) -> list[CuePoint]:
        return [c for c in self.cues if c.is_hot_cue]

    @property
    def memory_cues(self) -> list[CuePoint]:
        return [c for c in self.cues if c.is_memory_cue]

    @property
    def loops(self) -> list[CuePoint]:
        return [c for c in self.cues if c.is_loop]


class CueProposal(BaseModel):
    """Result of running cue generation strategy on a track."""

    track_id: int = Field(description="Track ID")
    hot_cues: list[CuePoint] = Field(description="Proposed hot cues")
    memory_cues: list[CuePoint] = Field(description="Proposed memory cues")
    confidence: dict[str, float] = Field(description="Confidence per pad letter (0.0-1.0)")
    notes: list[str] = Field(description="Human-readable explanations")


class Playlist(BaseModel):
    """A rekordbox playlist or folder."""

    id: str = Field(description="Playlist ID")
    name: str = Field(description="Playlist name")
    parent_id: str = Field(default="root", description="Parent playlist ID")
    seq: int = Field(default=0, description="Sequence number within parent")
    attribute: int = Field(default=0, description="0=playlist, 1=folder, 2=smart playlist")
    smart_list_xml: str | None = Field(default=None, description="Smart list XML if applicable")
    track_ids: list[int] = Field(default_factory=list, description="Track IDs in order")
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)

    @property
    def is_folder(self) -> bool:
        return self.attribute == 1

    @property
    def is_smart_playlist(self) -> bool:
        return self.attribute == 2

    @property
    def is_regular_playlist(self) -> bool:
        return self.attribute == 0


class ChangeSetItem(BaseModel):
    """A single change in a ChangeSet."""

    id: str = Field(default_factory=lambda: str(uuid4()))
    action: ChangeAction = Field(description="Action type")
    entity_type: str = Field(description="Entity type: cue, playlist, track")
    entity_id: str | int = Field(description="Entity identifier")
    old_data: dict[str, Any] | None = Field(default=None, description="Previous state")
    new_data: dict[str, Any] | None = Field(default=None, description="New state")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Additional metadata")


class ChangeSet(BaseModel):
    """A set of changes to be applied atomically."""

    id: str = Field(default_factory=lambda: str(uuid4()))
    name: str = Field(description="ChangeSet name/description")
    items: list[ChangeSetItem] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.now)
    applied_at: datetime | None = Field(default=None)
    rolled_back_at: datetime | None = Field(default=None)
    is_applied: bool = Field(default=False)
    is_rolled_back: bool = Field(default=False)
    dry_run: bool = Field(default=False)

    def add_change(
        self,
        action: ChangeAction,
        entity_type: str,
        entity_id: str | int,
        old_data: dict[str, Any] | None = None,
        new_data: dict[str, Any] | None = None,
        **metadata,
    ) -> ChangeSetItem:
        item = ChangeSetItem(
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            old_data=old_data,
            new_data=new_data,
            metadata=metadata,
        )
        self.items.append(item)
        return item


class AuditLogEntry(BaseModel):
    """Audit log entry for tracking all operations."""

    id: str = Field(default_factory=lambda: str(uuid4()))
    timestamp: datetime = Field(default_factory=datetime.now)
    operation: str = Field(description="Operation name (e.g., 'add_hot_cue')")
    entity_type: str = Field(description="Entity type")
    entity_id: str | int = Field(description="Entity identifier")
    user: str = Field(default="mcp", description="User/agent identifier")
    mode: OperationMode = Field(description="Operation mode at time of execution")
    changes: dict[str, Any] = Field(default_factory=dict, description="Change details")
    success: bool = Field(default=True)
    error: str | None = Field(default=None)
    changeset_id: str | None = Field(default=None)
    backup_id: str | None = Field(default=None)


class BackupInfo(BaseModel):
    """Backup metadata."""

    id: str = Field(default_factory=lambda: str(uuid4()))
    name: str = Field(description="Backup name")
    type: BackupType = Field(description="Backup type")
    path: str = Field(description="Backup file path")
    size_bytes: int = Field(description="Backup size in bytes")
    compressed_size_bytes: int = Field(description="Compressed size in bytes")
    created_at: datetime = Field(default_factory=datetime.now)
    db_version: str = Field(description="Database version/hash")
    is_protected: bool = Field(default=False, description="Protected from auto-cleanup")
    description: str = Field(default="", description="Backup description")
    changeset_id: str | None = Field(default=None, description="Associated ChangeSet")


class BackupUsage(BaseModel):
    """Backup storage usage statistics."""

    total_backups: int = Field(default=0)
    total_size_bytes: int = Field(default=0)
    total_compressed_bytes: int = Field(default=0)
    oldest_backup: datetime | None = Field(default=None)
    newest_backup: datetime | None = Field(default=None)
    protected_count: int = Field(default=0)
    full_backup_count: int = Field(default=0)
    differential_backup_count: int = Field(default=0)


class ServerStatus(BaseModel):
    """Server status information."""

    mode: OperationMode = Field(description="Current operation mode")
    db_connected: bool = Field(description="Whether database is connected")
    db_path: str | None = Field(default=None, description="Database path")
    rekordbox_running: bool = Field(description="Whether rekordbox is currently running")
    track_count: int = Field(default=0, description="Total tracks in library")
    playlist_count: int = Field(default=0, description="Total playlists")
    backup_usage: BackupUsage | None = Field(default=None, description="Backup usage stats")
    last_backup: datetime | None = Field(default=None, description="Last backup timestamp")


# Default cue profile instance
DEFAULT_CUE_PROFILE = CueProfile.default()
