"""Domain layer exports."""

from rekordbox_mcp.domain.models import (
    AuditLogEntry,
    BackupInfo,
    BackupType,
    BackupUsage,
    BeatGrid,
    ChangeAction,
    ChangeSet,
    ChangeSetItem,
    CueKind,
    CuePoint,
    CueProfile,
    CueProposal,
    CueSlotConfig,
    CueType,
    HotCueColorTableIndex,
    MemoryCueColor,
    Mood,
    OperationMode,
    Phrase,
    PhraseLabel,
    Playlist,
    ServerStatus,
    Track,
    WaveformPoint,
    DEFAULT_CUE_PROFILE,
)
from rekordbox_mcp.domain.cue import (
    CueManager,
    CuePosition,
    create_cue_position,
    get_cue_color_for_kind,
    get_next_available_hot_cue_slot,
    validate_cue_slot,
)
from rekordbox_mcp.domain.beatgrid import (
    BeatGrid as BeatGridDomain,
    create_beat_grid_from_analysis,
    estimate_beat_grid_from_bpm,
)
from rekordbox_mcp.domain.phrase import (
    PhraseAnalysisResult,
    analyze_phrases_from_anlz,
    create_default_phrases,
    find_phrases_after,
    find_phrases_before,
    find_phrases_by_label,
    get_nearest_phrase,
    get_phrase_at_position,
    resolve_phrase_label,
)
from rekordbox_mcp.domain.vocal import (
    PVDI_FRAME_MS,
    VocalAnalysisResult,
    VocalRegion,
    analyze_vocal_track,
    find_vocal_onset_after,
    find_vocal_onset_before,
    get_vocal_confidence_at,
    has_vocal_at,
    snap_to_vocal_phrase,
)
from rekordbox_mcp.domain.strategy import (
    CueStrategy,
    CueStrategyConfig,
    create_cue_strategy,
)
from rekordbox_mcp.domain.playlist import PlaylistManager
from rekordbox_mcp.domain.changeset import ChangeSetManager
from rekordbox_mcp.domain.backup import BackupManager
from rekordbox_mcp.domain.audit import AuditLogger

__all__ = [
    # Models
    "AuditLogEntry",
    "BackupInfo",
    "BackupType",
    "BackupUsage",
    "BeatGrid",
    "ChangeAction",
    "ChangeSet",
    "ChangeSetItem",
    "CueKind",
    "CuePoint",
    "CueProfile",
    "CueProposal",
    "CueSlotConfig",
    "CueType",
    "HotCueColorTableIndex",
    "MemoryCueColor",
    "Mood",
    "OperationMode",
    "Phrase",
    "PhraseLabel",
    "Playlist",
    "ServerStatus",
    "Track",
    "WaveformPoint",
    "DEFAULT_CUE_PROFILE",
    # Cue
    "CueManager",
    "CuePosition",
    "create_cue_position",
    "get_cue_color_for_kind",
    "get_next_available_hot_cue_slot",
    "validate_cue_slot",
    # BeatGrid
    "BeatGridDomain",
    "create_beat_grid_from_analysis",
    "estimate_beat_grid_from_bpm",
    # Phrase
    "PhraseAnalysisResult",
    "analyze_phrases_from_anlz",
    "create_default_phrases",
    "find_phrases_after",
    "find_phrases_before",
    "find_phrases_by_label",
    "get_nearest_phrase",
    "get_phrase_at_position",
    "resolve_phrase_label",
    # Vocal
    "PVDI_FRAME_MS",
    "VocalAnalysisResult",
    "VocalRegion",
    "analyze_vocal_track",
    "find_vocal_onset_after",
    "find_vocal_onset_before",
    "get_vocal_confidence_at",
    "has_vocal_at",
    "snap_to_vocal_phrase",
    # Strategy
    "CueStrategy",
    "CueStrategyConfig",
    "create_cue_strategy",
    # Playlist
    "PlaylistManager",
    # ChangeSet
    "ChangeSetManager",
    # Backup
    "BackupManager",
    # Audit
    "AuditLogger",
]