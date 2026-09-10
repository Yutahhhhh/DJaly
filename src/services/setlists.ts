import { apiClient, API_BASE_URL } from "./api-client";
import { Track } from "@/types";

export interface Setlist {
  id: number;
  name: string;
  description?: string;
  display_order: number;
  target_duration?: number | null;
  updated_at: string;
}

export interface SetlistTrack extends Track {
  setlist_track_id: number;
  position: number;
  wordplay_json?: string;
  in_ms: number;
  out_ms: number | null;
  playback_rate: number;
  extra_duration_ms: number;
  overlap_next_ms: number;
  revision: number;
}

// 保存用の型定義
export interface SetlistTrackUpdateItem {
  id: number;
  setlist_track_id?: number;
  track_id?: number;
  wordplay_json?: string | null;
  in_ms?: number;
  out_ms?: number | null;
  playback_rate?: number;
  extra_duration_ms?: number;
  overlap_next_ms?: number;
  revision?: number;
}

export const setlistsService = {
  getAll: async () => {
    return apiClient.get<Setlist[]>("/setlists");
  },
  create: async (name: string) => {
    return apiClient.post<Setlist>("/setlists", { name });
  },
  update: async (id: number, data: Partial<Setlist>) => {
    return apiClient.put<Setlist>(`/setlists/${id}`, data);
  },
  delete: async (id: number) => {
    return apiClient.delete(`/setlists/${id}`);
  },
  getTracks: async (id: number) => {
    return apiClient.get<SetlistTrack[]>(`/setlists/${id}/tracks`);
  },
  // trackData を IDとWordplayのオブジェクト配列を受け取れるように変更
  updateTracks: async (
    id: number,
    trackData: (number | SetlistTrackUpdateItem)[]
  ) => {
    return apiClient.post(`/setlists/${id}/tracks`, trackData);
  },
  updateWordplay: async (setlistTrackId: number, wordplayData: any) => {
    return apiClient.patch(`/setlist-tracks/${setlistTrackId}/wordplay`, {
      wordplay_json:
        typeof wordplayData === "string"
          ? wordplayData
          : JSON.stringify(wordplayData),
    });
  },

  deleteWordplay: async (setlistTrackId: number) => {
    return apiClient.patch(`/setlist-tracks/${setlistTrackId}/wordplay`, {
      wordplay_json: null,
    });
  },

  getExportUrl: (id: number) => {
    return `${API_BASE_URL}/setlists/${id}/export/m3u8`;
  },

  validateExport: async (id: number) => {
    return apiClient.get<{
      total: number;
      missing: { id: number; title?: string; artist?: string; filepath?: string }[];
    }>(`/setlists/${id}/export/validate`);
  },
  duration: (id: number) => apiClient.get<{ planned_duration_ms: number; full_duration_ms: number; unknown_entries: number; track_count: number }>(`/setlists/${id}/duration`),

  // --- Deterministic recommendation ---

  recommendNext: async (
    trackId: number,
    genres?: string[],
    subgenres?: string[]
  ) => {
    return apiClient.get<Track[]>("/recommendations/next", {
      track_id: trackId,
      genres: genres,
      subgenres: subgenres,
    });
  },

  generateAuto: async (
    length?: number,
    seedTrackIds?: number[],
    genres?: string[],
    subgenres?: string[]
  ) => {
    return apiClient.post<Track[]>("/recommendations/auto", {
      limit: length,
      seed_track_ids: seedTrackIds,
      genres: genres,
      subgenres: subgenres,
    });
  },

  generatePath: async (
    startTrackId: number,
    endTrackId: number,
    length: number,
    genres?: string[],
    subgenres?: string[]
  ) => {
    return apiClient.post<Track[]>("/recommendations/path", {
      start_track_id: startTrackId,
      end_track_id: endTrackId,
      length,
      genres: genres,
      subgenres: subgenres,
    });
  },
};
