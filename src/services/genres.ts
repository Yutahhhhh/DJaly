import { apiClient } from "./api-client";
import { Track } from "../types";

export interface TrackSuggestion {
  id: number;
  title: string;
  artist: string;
  bpm: number;
  filepath: string;
  current_genre?: string;
}

export interface GroupedSuggestion {
  parent_track: Track;
  suggestions: TrackSuggestion[];
}

export interface GroupedSuggestionSummary {
  parent_track: Track;
  suggestion_count: number;
}

export interface GenreBatchUpdateRequest {
  parent_track_id: number;
  target_track_ids: number[];
}

export interface GenreLLMAnalyzeRequest {
  track_id: number;
  overwrite?: boolean;
}

export interface GenreAnalysisResult {
  genre: string;
  reason: string;
  confidence: string;
}

export interface GenreUpdateResult {
  track_id: number;
  title: string;
  artist: string;
  old_genre: string;
  new_genre: string;
}

export interface GenreCleanupGroup {
  primary_genre: string;
  variant_genres: string[];
  track_count: number;
  suggestions: TrackSuggestion[];
}

export const genreService = {
  getAllGenres: async (): Promise<string[]> => {
    return apiClient.get<string[]>("/genres/list");
  },

  getUnknownTracks: async (
    offset: number = 0,
    limit: number = 50
  ): Promise<Track[]> => {
    return apiClient.get<Track[]>("/genres/unknown", { offset, limit });
  },

  getAllUnknownTrackIds: async (): Promise<number[]> => {
    return apiClient.get<number[]>("/genres/unknown-ids");
  },

  getGroupedSuggestions: async (
    offset: number = 0,
    limit: number = 10,
    threshold: number = 0.85
  ): Promise<GroupedSuggestionSummary[]> => {
    return apiClient.get<GroupedSuggestionSummary[]>(
      "/genres/grouped-suggestions",
      {
        offset,
        limit,
        threshold,
      }
    );
  },

  getSuggestionsForTrack: async (
    trackId: number,
    threshold: number = 0.85
  ): Promise<TrackSuggestion[]> => {
    return apiClient.get<TrackSuggestion[]>(
      `/genres/grouped-suggestions/${trackId}`,
      {
        threshold,
      }
    );
  },

  analyzeTrackWithLlm: async (
    trackId: number,
    overwrite: boolean = false
  ): Promise<GenreAnalysisResult> => {
    return apiClient.post<GenreAnalysisResult>("/genres/llm-analyze", {
      track_id: trackId,
      overwrite,
    });
  },

  analyzeTracksBatchWithLlm: async (
    trackIds: number[]
  ): Promise<GenreUpdateResult[]> => {
    return apiClient.post<GenreUpdateResult[]>("/genres/batch-llm-analyze", {
      track_ids: trackIds,
    });
  },

  batchUpdateGenres: async (
    parentTrackId: number,
    targetTrackIds: number[]
  ): Promise<{ updated_count: number; genre: string }> => {
    return apiClient.post<{ updated_count: number; genre: string }>(
      "/genres/batch-update",
      {
        parent_track_id: parentTrackId,
        target_track_ids: targetTrackIds,
      }
    );
  },

  startAnalyzeAll: async (
    mode: "keep" | "overwrite"
  ): Promise<{ status: string; message: string }> => {
    return apiClient.post<{ status: string; message: string }>(
      "/genres/analyze-all",
      { mode }
    );
  },

  getCleanupSuggestions: async (): Promise<GenreCleanupGroup[]> => {
    return apiClient.get<GenreCleanupGroup[]>("/genres/cleanup-suggestions");
  },

  executeCleanup: async (
    targetGenre: string,
    trackIds: number[]
  ): Promise<{ updated_count: number; genre: string }> => {
    return apiClient.post<{ updated_count: number; genre: string }>(
      "/genres/cleanup-execute",
      {
        target_genre: targetGenre,
        track_ids: trackIds,
      }
    );
  },

  applyGenresToFiles: async (
    trackIds: number[]
  ): Promise<{ success: number; failed: number }> => {
    return apiClient.post<{ success: number; failed: number }>(
      "/genres/apply-to-files",
      { track_ids: trackIds }
    );
  },
};
