import { apiClient } from "./api-client";
import { Track } from "@/types";

export interface KeywordAnalysis {
  keyword: string;
  count: number;
}

export interface AnalysisResult {
  words: KeywordAnalysis[];
  phrases: KeywordAnalysis[];
}

// Matches backend API response
export interface LyricSnippet {
  track: Track;
  snippet: string[];
  match_line: number;
}

export const lyricsService = {
  // 楽曲の歌詞を取得
  getLyrics: (trackId: number) =>
    apiClient.get<{ content: string }>(`/tracks/${trackId}/lyrics`),

  // 歌詞を分析（頻出単語・フレーズ）
  analyzeLyrics: (trackId: number) =>
    apiClient.post<AnalysisResult>(`/tracks/${trackId}/lyrics/analyze`, {}),

  // 歌詞を検索
  searchLyrics: (query: string, excludeTrackId?: number) => {
    const params: any = { q: query };
    if (excludeTrackId) {
      params.exclude_track_id = excludeTrackId;
    }
    return apiClient.get<LyricSnippet[]>("/lyrics/search", params);
  },
};
