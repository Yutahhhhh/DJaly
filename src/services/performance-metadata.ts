import { apiClient } from "./api-client";
import type {
  PerformanceMetadata,
  PerformanceMetadataWrite,
  PerformanceBeatGrid,
} from "@/types/performance-metadata";


export interface RekordboxCueImportIssue {
  track_id: number;
  message: string;
}

export interface RekordboxCueImportSummary {
  imported: number;
  skipped: number;
  failed: number;
  conflicts: number;
  errors: RekordboxCueImportIssue[];
  errors_truncated: number;
}


export const performanceMetadataService = {
  analyzeGrid: (trackId: number, force = false) => apiClient.post<PerformanceBeatGrid>(`/tracks/${trackId}/grid-analysis`, { force }),
  rekordboxGrid: (trackId: number) => apiClient.post<PerformanceBeatGrid>(`/tracks/${trackId}/grid-rekordbox`, {}),
  importRekordboxCues: (trackId: number, revision: number) =>
    apiClient.post<PerformanceMetadata>(`/tracks/${trackId}/cues-rekordbox`, { revision }),
  importAllRekordboxCues: () =>
    apiClient.post<RekordboxCueImportSummary>(
      "/tracks/cues-rekordbox/import",
      {},
      15 * 60_000,
    ),
  /**
   * 一覧向けに、複数トラックのホットキュー位置だけをまとめて引く。
   * `get` と違いグリッド解析にフォールバックしないので行数分呼んでも軽い。
   * 返る形は 8 スロットの配列で、そのままプレビュー波形へ渡せる。
   */
  cuePoints: async (trackIds: number[]): Promise<Record<number, (number | null)[]>> => {
    if (!trackIds.length) return {};
    const raw = await apiClient.post<Record<string, (number | null)[]>>(
      "/tracks/performance-metadata/cue-points",
      { track_ids: trackIds.slice(0, 500) },
    );
    return Object.fromEntries(Object.entries(raw).map(([id, positions]) => [Number(id), positions]));
  },

  get: (trackId: number) =>
    apiClient.get<PerformanceMetadata>(`/tracks/${trackId}/performance-metadata`),

  replace: (trackId: number, metadata: PerformanceMetadataWrite) =>
    apiClient.put<PerformanceMetadata>(
      `/tracks/${trackId}/performance-metadata`,
      metadata,
    ),
};
