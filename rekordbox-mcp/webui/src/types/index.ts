// TypeScript mirrors of rekordbox_mcp.domain.models (Pydantic models).

export type OperationMode = "readonly" | "xml" | "masterdb";

export type BackupType = "full" | "differential" | "protected";

export type ChangeAction = "create" | "update" | "delete" | "replace" | "merge";

export interface ChangeSetItem {
  id: string;
  action: ChangeAction;
  entity_type: string;
  entity_id: string | number;
  old_data: Record<string, unknown> | null;
  new_data: Record<string, unknown> | null;
  metadata: Record<string, unknown>;
}

export interface ChangeSet {
  id: string;
  name: string;
  items?: ChangeSetItem[];
  item_count: number;
  created_at: string;
  applied_at?: string | null;
  rolled_back_at?: string | null;
  is_applied: boolean;
  is_rolled_back: boolean;
  dry_run?: boolean;
}

export interface AuditLogEntry {
  id: string;
  timestamp: string;
  operation: string;
  entity_type: string;
  entity_id: string | number;
  user: string;
  mode: OperationMode;
  changes: Record<string, unknown>;
  success: boolean;
  error: string | null;
  changeset_id: string | null;
  backup_id: string | null;
}

export type PhraseLabel =
  | "Intro"
  | "Up"
  | "Down"
  | "Chorus"
  | "Verse1"
  | "Verse2"
  | "Verse3"
  | "Verse4"
  | "Verse5"
  | "Verse6"
  | "Bridge"
  | "Outro"
  | "Unknown";

/** CueKind: 0=memory, 1-9=hot cue slots (matches rekordbox DB Kind column). */
export type CueKind = number;

export interface BeatGrid {
  first_beat_ms: number;
  bpm: number;
}

export interface CuePoint {
  id: string;
  track_id: number;
  kind: CueKind;
  position_ms: number;
  loop_end_ms: number | null;
  color_table_index: number | null;
  color: number;
  comment: string;
  created_at: string;
  updated_at: string;
}

export interface Phrase {
  beat_start: number;
  beat_end: number;
  kind: number;
  label: PhraseLabel | string;
  position_ms: number;
  duration_ms: number;
  mood: number;
}

export interface WaveformPoint {
  height: number;
  red: number;
  green: number;
  blue: number;
}

export interface Track {
  id: number;
  title: string;
  artist: string;
  bpm: number;
  duration_ms: number;
  analysis_path: string;
  key?: string | null;
  genre?: string | null;
  cues: CuePoint[];
  phrases: Phrase[];
  beat_grid: BeatGrid | null;
  waveform: WaveformPoint[] | null;
  vocal_track: number[] | null;
}

export interface CueProposal {
  track_id: number;
  hot_cues: CuePoint[];
  memory_cues: CuePoint[];
  confidence: Record<string, number>;
  notes: string[];
}

export interface Playlist {
  id: string;
  name: string;
  parent_id: string;
  seq: number;
  attribute: number;
  smart_list_xml: string | null;
  track_ids: number[];
  created_at: string;
  updated_at: string;
}

export interface BackupInfo {
  id: string;
  name: string;
  type: BackupType;
  path: string;
  size_bytes: number;
  compressed_size_bytes: number;
  created_at: string;
  db_version: string;
  is_protected: boolean;
  description: string;
  changeset_id: string | null;
}

export interface BackupUsage {
  total_backups: number;
  total_size_bytes: number;
  total_compressed_bytes: number;
  oldest_backup: string | null;
  newest_backup: string | null;
  protected_count: number;
  full_backup_count: number;
  differential_backup_count: number;
}

export interface ServerStatus {
  mode: OperationMode;
  db_connected: boolean;
  db_path: string | null;
  rekordbox_running: boolean;
  track_count: number;
  playlist_count: number;
  backup_usage: BackupUsage | null;
  last_backup: string | null;
}

export interface GetCuesResponse {
  track_id: number;
  cues: CuePoint[];
  hot_cues: CuePoint[];
  memory_cues: CuePoint[];
  loops: CuePoint[];
}

export interface GenerateCuesResponse {
  success: boolean;
  track_id: number;
  generated_count: number;
  cues: CuePoint[];
  confidence: Record<string, number>;
  notes: string[];
}
