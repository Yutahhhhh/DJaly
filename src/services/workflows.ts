import { apiClient } from "./api-client";
import { currentAnalysisProfile, type AnalysisProfile } from "./analysis-profile";

export type RepairItem = {
  track_id: number; title?: string; artist?: string; old_path: string;
  access_state: "available" | "missing"; candidate_path?: string | null;
  candidate_state: string; reason: string;
};
export type RepairPlan = { id: string; state: string; items: RepairItem[]; summary: Record<string, number> };
export type VersionGroup = { id: number; name?: string; preferred_track_id: number; revision: number; members: Array<Record<string, unknown>> };
export type AudioPreset = { id: string; name: string; config: Record<string, unknown>; revision: number; updated_at: string };
export type ControllerProfile = { id: string; name: string; adapterId: "generic-midi" | "ddj400" | "ddj1000"; bindings: Array<Record<string, unknown>>; builtIn?: boolean; revision?: number; [key: string]: unknown };
export type UsbExport = { id: string; setlist_id: number; state: string; handoff_path: string; snapshot_hash: string; stale?: boolean; verification_json?: string; limitations?: string[] };
export type UsbDevice = { id: string; label: string; mount_path: string; filesystem?: string; capacity_bytes?: number; free_bytes?: number; read_only: boolean; connected: boolean };
export type ImportBatch = { progress?: { stage: string; label: string; filepath: string; started_at: number } | null; id: string; request_id: string; state: string; analysis_profile?: AnalysisProfile; effective_analysis_profile?: "light" | "full" | null; total_items: number; succeeded_items: number; failed_items: number; skipped_items: number; queued_items?: number; current_file?: string | null; target_name_snapshot?: string; target_kind: string; target_id?: number; created_at?: string; updated_at?: string; items?: Array<Record<string, unknown>> };
export type TimelineSegment = { id?: number; track_id?: number | null; deck?: string | null; start_ms: number; end_ms?: number | null; title_snapshot?: string; artist_snapshot?: string; version_snapshot?: string | null; source?: string };

export const workflowsService = {
  summary: () => apiClient.get<Record<string, number>>("/workflows/summary"),
  diagnoseMedia: (body: { track_ids?: number[]; old_root?: string; new_root?: string }) => apiClient.post<RepairPlan>("/workflows/media/diagnose", body),
  applyRepair: (id: string, selections: Record<string, string>) => apiClient.post(`/workflows/media/repairs/${id}/apply`, { selections }),
  undoRepair: (id: string) => apiClient.post(`/workflows/media/repairs/${id}/undo`, {}),
  createVersionGroup: (trackIds: number[], name?: string) => apiClient.post<VersionGroup>("/workflows/version-groups", { track_ids: trackIds, name }),
  updateVersionGroup: (group: VersionGroup) => apiClient.patch<VersionGroup>(`/workflows/version-groups/${group.id}`, { revision: group.revision, name: group.name, preferred_track_id: group.preferred_track_id, members: group.members }),
  versionsForTrack: (trackId: number) => apiClient.get<VersionGroup | null>(`/workflows/tracks/${trackId}/versions`),
  swapSetlistVersion: (entryId: number, newTrackId: number, revision: number) => apiClient.patch(`/workflows/setlist-entries/${entryId}/version`, { new_track_id: newTrackId, revision }),
  createBackup: (destination: string, includeMedia: boolean, includeRecordings: boolean) => apiClient.post("/workflows/backups", { destination, include_media: includeMedia, include_recordings: includeRecordings, ui_settings: Object.fromEntries(Object.entries(localStorage)) }, 30 * 60_000),
  inspectBackup: (path: string) => apiClient.post<Record<string, unknown>>("/workflows/restore/inspect", { path }),
  restoreBackup: (path: string) => apiClient.post<{restored:boolean;ui_settings:Record<string,string>}>("/workflows/restore/apply", { path, confirmed: true }, 30 * 60_000),
  audioPresets: () => apiClient.get<AudioPreset[]>("/workflows/audio-presets"),
  saveAudioPreset: (name: string, config: Record<string, unknown>, id?: string, revision?: number) => apiClient.put<AudioPreset>("/workflows/audio-presets", { id, revision, name, config }),
  deleteAudioPreset: (id: string) => apiClient.delete(`/workflows/audio-presets/${id}`),
  controllerProfiles: () => apiClient.get<ControllerProfile[]>("/workflows/controller-profiles"),
  saveControllerProfile: (profile: Record<string, unknown>) => apiClient.put<ControllerProfile>("/workflows/controller-profiles", profile),
  createUsbHandoff: (setlistId: number, usbDeviceId?: string) => apiClient.post<UsbExport>("/workflows/usb/handoffs", { setlist_id: setlistId, usb_device_id: usbDeviceId }),
  usbDevices: () => apiClient.get<UsbDevice[]>("/workflows/usb/devices"),
  ejectUsb: (id: string) => apiClient.post(`/workflows/usb/devices/${encodeURIComponent(id)}/eject`, {}),
  usbHandoffs: () => apiClient.get<UsbExport[]>("/workflows/usb/handoffs"),
  duplicateUsbHandoff: (id: string, usbDeviceId?: string) => apiClient.post<UsbExport>(`/workflows/usb/handoffs/${id}/duplicate`, { usb_device_id: usbDeviceId }),
  verifyUsbHandoff: (id: string, evidence: Record<string, unknown>) => apiClient.post(`/workflows/usb/handoffs/${id}/verify`, evidence),
  createImport: (
    paths: string[],
    target: { kind: "collection" | "local_playlist"; id?: number },
    origin: "native_file_drop" | "file_picker" = "file_picker",
    analysisProfile: AnalysisProfile = currentAnalysisProfile(),
  ) => apiClient.post<ImportBatch>("/workflows/play/imports", {
    request_id: crypto.randomUUID(),
    paths,
    target,
    origin,
    analysis_profile: analysisProfile,
  }, 30 * 60_000),
  imports: (active = false) => apiClient.get<ImportBatch[]>("/workflows/play/imports", { active }, 5000),
  importStatus: (id: string) => apiClient.get<ImportBatch>(`/workflows/play/imports/${id}`),
  controlImport: (id: string, action: "pause" | "resume" | "cancel" | "retry") => apiClient.post<ImportBatch>(`/workflows/play/imports/${id}/${action}`, {}),
  timeline: (recordingId: number) => apiClient.get<TimelineSegment[]>(`/workflows/recordings/${recordingId}/timeline`),
  replaceTimeline: (recordingId: number, revision: number, segments: TimelineSegment[]) => apiClient.put<TimelineSegment[]>(`/workflows/recordings/${recordingId}/timeline`, { revision, segments }),
  saveEngineTimeline: (recordingId: number, body: { sample_rate_hz: number; frame_count: number; dropped_events: number; segments: Array<Record<string, unknown>> }) => apiClient.post<TimelineSegment[]>(`/workflows/recordings/${recordingId}/timeline/engine`, body),
  tracklistTextUrl: (recordingId: number) => `${apiClient.baseUrl}/workflows/recordings/${recordingId}/tracklist.txt`,
  registerExternalRecording: (body: { filepath: string; title: string; artist: string }) => apiClient.post<{id:number;recording_key:string;duration_ms:number}>("/workflows/recordings/external", body),
};
