import { Button } from "@/components/ui/button";
import { Plus } from "lucide-react";
import { Prompt } from "./types";

interface PromptListProps {
  prompts: Prompt[];
  selectedPrompt: Prompt | null;
  onSelect: (prompt: Prompt) => void;
  onCreate: () => void;
}

export function PromptList({
  prompts,
  selectedPrompt,
  onSelect,
  onCreate,
}: PromptListProps) {
  return (
    <div className="w-1/3 flex flex-col gap-4">
      <div className="flex items-center justify-between">
        <h2 className="text-xl font-bold">Prompts</h2>
        <Button size="sm" onClick={onCreate}>
          <Plus className="h-4 w-4" />
        </Button>
      </div>
      <div className="flex-1 border rounded-md overflow-y-auto p-2 space-y-2">
        {prompts.map((prompt) => (
          <div
            key={prompt.id}
            className={`p-3 rounded-md cursor-pointer border ${
              selectedPrompt?.id === prompt.id ? "bg-accent" : "hover:bg-muted"
            }`}
            onClick={() => onSelect(prompt)}
          >
            <div className="font-medium">{prompt.name}</div>
            {prompt.is_default && (
              <span className="text-xs text-muted-foreground">Default</span>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
