import { apiClient } from "./api-client";

export interface Preset {
  id: number;
  name: string;
  description: string;
  preset_type: "search" | "generation" | "all";
  prompt_id?: number;
  prompt_content?: string; // APIから返される
}

export const presetsService = {
  getAll: async (type?: "search" | "generation", strict: boolean = false) => {
    return apiClient.get<Preset[]>("/presets", { type, strict });
  },
  create: async (preset: Partial<Preset>) => {
    return apiClient.post<Preset>("/presets", preset);
  },
  update: async (id: number, preset: Partial<Preset>) => {
    return apiClient.put<Preset>(`/presets/${id}`, preset);
  },
  delete: async (id: number) => {
    return apiClient.delete(`/presets/${id}`);
  },
};
