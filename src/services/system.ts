import { apiClient } from "./api-client";
import { Setlist } from "./setlists";

export interface DashboardStats {
  total_tracks: number;
  analyzed_tracks: number;
  unanalyzed_tracks: number;
  genre_distribution: {
    name: string;
    count: number;
  }[];
  unverified_genres_count: number;
  lyrics_tracks_count: number;
  recent_setlists: Setlist[];
  config: {
    has_root_path: boolean;
    llm_model: string;
    llm_configured: boolean;
  };
}

export interface SystemHealth {
  status: string;
  duckdb_version: string;
  ollama_status: string;
}

export const systemService = {
  getHealth: async () => {
    return apiClient.get<SystemHealth>("/");
  },
  getDashboardStats: async () => {
    return apiClient.get<DashboardStats>("/dashboard");
  },
};
