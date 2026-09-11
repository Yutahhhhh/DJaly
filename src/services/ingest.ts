import { apiClient } from "./api-client";
import type { IngestMessage } from "./ingestion-socket";

type IngestResponse = {
  status: "success" | "error";
  message?: string;
  state?: IngestMessage;
};

export const ingestService = {
  ingest: async (targets: string[], forceUpdate: boolean) => {
    return apiClient.post<IngestResponse>("/ingest", { targets, force_update: forceUpdate });
  },
  cancel: async () => {
    return apiClient.post<IngestResponse>("/ingest/cancel", {});
  },
};
