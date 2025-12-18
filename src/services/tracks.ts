import { apiClient } from "./api-client";
import { Track } from "@/types";

export const tracksService = {
  getTracks: async (params: Record<string, string | number | boolean | null | undefined | string[]>) => {
    return apiClient.get<Track[]>("/tracks", params);
  },
  getSimilarTracks: async (trackId: number, limit: number = 20) => {
    return apiClient.get<Track[]>(`/tracks/${trackId}/similar`, { limit });
  },
  updateGenre: async (trackId: number, genre: string) => {
    return apiClient.patch<Track>(`/tracks/${trackId}/genre`, { genre });
  },
  suggestGenre: async (trackId: number) => {
    return apiClient.get<{ suggested_genre: string | null, reason?: string }>(`/tracks/${trackId}/suggest-genre`);
  },
};
