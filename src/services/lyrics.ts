import { apiClient } from "./api-client";
import { Track } from "@/types";

export interface KeywordMatch {
  keyword: string;
  count: number;
}

export interface LyricSnippet {
  track: Track;
  snippet: string[];
  timestamp: number | null;
  matched_text: string;
}

export const lyricsService = {
  getLyrics: (trackId: number) =>
    apiClient.get<{ content: string }>(`/tracks/${trackId}/lyrics`),

  analyzeLyrics: (trackId: number) =>
    apiClient.post<KeywordMatch[]>(`/tracks/${trackId}/lyrics/analyze`, {}),

  searchLyrics: (query: string, excludeTrackId?: number) => {
    const params: any = { q: query };
    if (excludeTrackId) {
      params.exclude_track_id = excludeTrackId;
    }
    return apiClient.get<LyricSnippet[]>("/lyrics/search", params);
  },
};
