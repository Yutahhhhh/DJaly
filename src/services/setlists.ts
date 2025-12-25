import { apiClient, API_BASE_URL } from "./api-client";
import { Track } from "@/types";

export interface Setlist {
  id: number;
  name: string;
  description?: string;
  display_order: number;
  updated_at: string;
}

export interface SetlistTrack extends Track {
  setlist_track_id: number;
  position: number;
  wordplay_json?: string;
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
  updateTracks: async (id: number, trackIds: number[]) => {
    return apiClient.post(`/setlists/${id}/tracks`, trackIds);
  },
  updateWordplay: async (setlistTrackId: number, wordplayData: any) => {
    return apiClient.patch(`/setlist-tracks/${setlistTrackId}/wordplay`, { wordplay_json: JSON.stringify(wordplayData) });
  },

  getExportUrl: (id: number) => {
    return `${API_BASE_URL}/setlists/${id}/export/m3u8`;
  },

  // --- AI / Recommendation ---

  recommendNext: async (
    trackId: number,
    presetId?: number,
    genres?: string[]
  ) => {
    return apiClient.get<Track[]>("/recommendations/next", {
      track_id: trackId,
      preset_id: presetId,
      genres: genres,
    });
  },

  generateAuto: async (
    presetId: number,
    limit: number,
    seedTrackIds?: number[],
    genres?: string[]
  ) => {
    return apiClient.post<Track[]>("/recommendations/auto", {
      preset_id: presetId,
      limit,
      seed_track_ids: seedTrackIds,
      genres: genres,
    });
  },

  generatePath: async (
    startTrackId: number,
    endTrackId: number,
    length: number,
    genres?: string[]
  ) => {
    return apiClient.post<Track[]>("/recommendations/path", {
      start_track_id: startTrackId,
      end_track_id: endTrackId,
      length,
      genres,
    });
  },
};
