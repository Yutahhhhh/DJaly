export interface Prompt {
  id: number;
  name: string;
  content: string;
  is_default: boolean;
}

export interface Preset {
  id: number;
  name: string;
  description: string;
  preset_type: "search" | "generation" | "all";
  prompt_id?: number;
  prompt_content?: string;
}
