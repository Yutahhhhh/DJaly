import { apiClient } from "./api-client";
import type { IngestMessage } from "./ingestion-socket";
import { currentAnalysisProfile, type AnalysisProfile } from "./analysis-profile";

type IngestResponse = {
  status: "success" | "error";
  message?: string;
  state?: IngestMessage;
};

export const ingestService = {
  ingest: async (
    targets: string[],
    forceUpdate: boolean,
    analysisProfile: AnalysisProfile = currentAnalysisProfile(),
  ) => {
    return apiClient.post<IngestResponse>("/ingest", {
      targets,
      force_update: forceUpdate,
      analysis_profile: analysisProfile,
    });
  },
  cancel: async () => {
    return apiClient.post<IngestResponse>("/ingest/cancel", {});
  },
};
