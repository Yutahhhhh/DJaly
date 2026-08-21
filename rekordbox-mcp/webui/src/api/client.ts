import type {
  BackupInfo,
  BackupType,
  BackupUsage,
  BeatGrid,
  CuePoint,
  ChangeSet,
  ChangeSetItem,
  AuditLogEntry,
  GenerateCuesResponse,
  GetCuesResponse,
  OperationMode,
  Phrase,
  Playlist,
  ServerStatus,
  Track,
  WaveformPoint,
} from "../types";

const BASE = "/api";

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
    this.name = "ApiError";
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail ?? detail;
    } catch {
      // ignore body parse failure
    }
    throw new ApiError(res.status, detail);
  }
  return res.json() as Promise<T>;
}

// ---------------------------------------------------------------------------
// System / mode
// ---------------------------------------------------------------------------

export async function getStatus(): Promise<ServerStatus> {
  const data = await request<{ success: boolean; status: ServerStatus }>("/status");
  return data.status;
}

export async function getMode(): Promise<{ mode: OperationMode; description: string }> {
  return request("/mode");
}

export async function setMode(mode: OperationMode): Promise<{
  success: boolean;
  mode: OperationMode;
  previous_mode?: OperationMode;
  message: string;
}> {
  return request("/mode", { method: "PUT", body: JSON.stringify({ mode }) });
}

// ---------------------------------------------------------------------------
// Cues
// ---------------------------------------------------------------------------

export async function getCues(trackId: number): Promise<GetCuesResponse> {
  return request(`/cues/${trackId}`);
}

export async function generateCues(
  trackId: number,
  profile: string = "default",
  mode: "replace" | "merge" | "preserve" = "preserve",
): Promise<GenerateCuesResponse> {
  return request(`/cues/${trackId}/generate`, {
    method: "POST",
    body: JSON.stringify({ profile, mode }),
  });
}

export async function addHotCue(params: {
  track_id: number;
  position_ms: number;
  kind?: number;
  name?: string;
  color_table_index?: number | null;
  loop_end_ms?: number | null;
}): Promise<{ success: boolean; cue: CuePoint }> {
  return request("/cues/hot", { method: "POST", body: JSON.stringify(params) });
}

export async function addMemoryCue(params: {
  track_id: number;
  position_ms: number;
  name?: string;
  color?: number;
  loop_end_ms?: number | null;
}): Promise<{ success: boolean; cue: CuePoint }> {
  return request("/cues/memory", { method: "POST", body: JSON.stringify(params) });
}

export async function addLoop(params: {
  track_id: number;
  position_ms: number;
  loop_end_ms: number;
  kind?: number;
  name?: string;
}): Promise<{ success: boolean; cue: CuePoint }> {
  return request("/cues/loop", { method: "POST", body: JSON.stringify(params) });
}

export async function updateCue(
  cueId: string,
  params: {
    track_id: number;
    position_ms?: number | null;
    name?: string | null;
    color_table_index?: number | null;
    color?: number | null;
    loop_end_ms?: number | null;
  },
): Promise<{ success: boolean; cue: CuePoint | null }> {
  return request(`/cues/${cueId}`, { method: "PUT", body: JSON.stringify(params) });
}

export async function deleteCue(
  cueId: string,
  trackId: number,
): Promise<{ success: boolean; cue_id: string }> {
  return request(`/cues/${cueId}?track_id=${trackId}`, { method: "DELETE" });
}

export async function snapCueToBeatgrid(
  trackId: number,
  cueId: string,
  grid: "beat" | "bar" = "beat",
): Promise<{ success: boolean; cue: CuePoint | null }> {
  return request(`/cues/${trackId}/snap?cue_id=${cueId}&grid=${grid}`, { method: "POST" });
}

// ---------------------------------------------------------------------------
// Tracks
// ---------------------------------------------------------------------------

export async function getTrack(trackId: number): Promise<Track> {
  const data = await request<{ success: boolean; track: Track }>(`/tracks/${trackId}`);
  return data.track;
}

export async function getTrackAnalysis(trackId: number): Promise<{
  track_id: number;
  phrases: Phrase[];
  beat_grid: BeatGrid | null;
  waveform: WaveformPoint[];
  vocal_track: number[] | null;
}> {
  return request(`/tracks/${trackId}/analysis`);
}

// ---------------------------------------------------------------------------
// Playlists
// ---------------------------------------------------------------------------

export async function getPlaylists(): Promise<Playlist[]> {
  const data = await request<{ playlists: Playlist[]; count: number }>("/playlists");
  return data.playlists;
}

export async function getPlaylistTracks(
  playlistId: string,
): Promise<{ playlist_id: string; playlist_name: string | null; track_ids: number[]; count: number }> {
  return request(`/playlists/${playlistId}/tracks`);
}

// ---------------------------------------------------------------------------
// Backups
// ---------------------------------------------------------------------------

export async function getBackups(type: BackupType | "all" = "all"): Promise<BackupInfo[]> {
  const data = await request<{ backups: BackupInfo[]; count: number }>(`/backups?type=${type}`);
  return data.backups;
}

export async function getBackupUsage(): Promise<BackupUsage> {
  const data = await request<{ success: boolean; usage: BackupUsage }>("/backups/usage");
  return data.usage;
}

// ---------------------------------------------------------------------------
// ChangeSets / audit log
// ---------------------------------------------------------------------------

export async function createChangeset(name: string): Promise<ChangeSet> {
  const data = await request<{ success: boolean; changeset: ChangeSet }>("/changesets", {
    method: "POST",
    body: JSON.stringify({ name }),
  });
  return data.changeset;
}

export async function listChangesets(): Promise<ChangeSet[]> {
  const data = await request<{ changesets: ChangeSet[]; count: number }>("/changesets");
  return data.changesets;
}

export async function previewChangeset(changesetId: string): Promise<ChangeSet & { changes: ChangeSetItem[] }> {
  const data = await request<{ success: boolean; preview: ChangeSet & { changes: ChangeSetItem[] } }>(
    `/changesets/${encodeURIComponent(changesetId)}/preview`,
  );
  return data.preview;
}

export async function applyChangeset(changesetId: string, dryRun: boolean): Promise<{
  success: boolean;
  changeset_id?: string;
  applied_count?: number;
  dry_run?: boolean;
  backup_id?: string | null;
  error?: string;
}> {
  return request(`/changesets/${encodeURIComponent(changesetId)}/apply`, {
    method: "POST",
    body: JSON.stringify({ dry_run: dryRun }),
  });
}

export async function undoChangeset(changesetId: string): Promise<Record<string, unknown> & { success: boolean; error?: string }> {
  return request(`/changesets/${encodeURIComponent(changesetId)}/undo`, { method: "POST" });
}

export async function rollbackChangeset(changesetId: string): Promise<Record<string, unknown> & { success: boolean; error?: string }> {
  return request(`/changesets/${encodeURIComponent(changesetId)}/rollback`, { method: "POST" });
}

export async function getAuditLog(): Promise<AuditLogEntry[]> {
  const data = await request<{ logs: AuditLogEntry[]; count: number }>("/audit-log");
  return data.logs;
}
