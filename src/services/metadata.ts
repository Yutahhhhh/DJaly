import { apiClient } from "./api-client";

export interface FileMetadata {
  artwork: string | null;
  lyrics: string;
  waveform_peaks?: number[];
  beat_positions?: number[];
}

export const metadataService = {
  // ファイルからメタデータを取得
  getMetadata: (trackId: number) =>
    apiClient.get<FileMetadata>(`/metadata?track_id=${trackId}`),

  // 物理ファイルのタグ（歌詞・アートワーク）を更新
  updateMetadata: (
    trackId: number,
    updates: { lyrics?: string; artwork_data?: string }
  ) => apiClient.patch(`/metadata/update`, { track_id: trackId, ...updates }),

  // LLMを使用したコンテンツ取得（個別のエンドポイント）
  fetchLyrics: (trackId: number) =>
    apiClient.post<{ lyrics: string }>(`/metadata/fetch-lyrics`, {
      track_id: trackId,
    }),

  fetchArtworkInfo: (trackId: number) =>
    apiClient.post<{ info: string }>(`/metadata/fetch-artwork-info`, {
      track_id: trackId,
    }),
};
