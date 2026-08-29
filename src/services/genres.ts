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

export type AnalysisMode = "genre" | "subgenre" | "both";

export interface GenreAnalysisResult {
  genre: string;
  subgenre?: string;
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

  getAllSubgenres: async (): Promise<string[]> => {
    return apiClient.get<string[]>("/genres/subgenres");
  },

  getUnknownTracks: async (
    offset: number = 0,
    limit: number = 50,
    mode: AnalysisMode = "genre"
  ): Promise<Track[]> => {
    return apiClient.get<Track[]>("/genres/unknown", { offset, limit, mode });
  },

  getAllUnknownTrackIds: async (mode: AnalysisMode = "genre"): Promise<number[]> => {
    return apiClient.get<number[]>("/genres/unknown-ids", { mode });
  },

  getGroupedSuggestions: async (
    offset: number = 0,
    limit: number = 10,
    threshold: number = 0.85,
    mode: AnalysisMode = "genre"
  ): Promise<GroupedSuggestionSummary[]> => {
    return apiClient.get<GroupedSuggestionSummary[]>(
      "/genres/grouped-suggestions",
      {
        offset,
        limit,
        threshold,
        mode,
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

  getCleanupSuggestions: async (mode: AnalysisMode = "genre"): Promise<GenreCleanupGroup[]> => {
    return apiClient.get<GenreCleanupGroup[]>("/genres/cleanup-suggestions", { mode });
  },

  executeCleanup: async (
    targetGenre: string,
    trackIds: number[],
    mode: AnalysisMode = "genre"
  ): Promise<{ updated_count: number; genre: string }> => {
    return apiClient.post<{ updated_count: number; genre: string }>(
      "/genres/cleanup-execute",
      {
        target_genre: targetGenre,
        track_ids: trackIds,
        mode,
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
