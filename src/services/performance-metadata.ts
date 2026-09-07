import { apiClient } from "./api-client";
import type {
  PerformanceMetadata,
  PerformanceMetadataWrite,
} from "@/types/performance-metadata";


export const performanceMetadataService = {
  get: (trackId: number) =>
    apiClient.get<PerformanceMetadata>(`/tracks/${trackId}/performance-metadata`),

  replace: (trackId: number, metadata: PerformanceMetadataWrite) =>
    apiClient.put<PerformanceMetadata>(
      `/tracks/${trackId}/performance-metadata`,
      metadata,
    ),
};
