import { apiClient } from "./api-client";
import { Prompt } from "@/components/prompt-manager/types";

export const promptsService = {
  getAll: async () => {
    return apiClient.get<Prompt[]>("/prompts");
  },
  create: async (prompt: Partial<Prompt>) => {
    return apiClient.post<Prompt>("/prompts", prompt);
  },
  update: async (id: number, prompt: Partial<Prompt>) => {
    return apiClient.put<Prompt>(`/prompts/${id}`, prompt);
  },
  delete: async (id: number) => {
    return apiClient.delete(`/prompts/${id}`);
  },
};
