import { apiClient } from "./api-client";

export const ingestService = {
  ingest: async (targets: string[], forceUpdate: boolean) => {
    return apiClient.post("/ingest", { targets, force_update: forceUpdate });
  },
  cancel: async () => {
    return apiClient.post("/ingest/cancel", {});
  },
};
