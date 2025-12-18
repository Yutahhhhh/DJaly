import { apiClient } from "./api-client";
import { FileItem } from "@/components/file-explorer/types";

export const filesystemService = {
  list: async (path: string, hideAnalyzed: boolean) => {
    return apiClient.post<FileItem[]>("/fs/list", { path, hide_analyzed: hideAnalyzed });
  },
};
