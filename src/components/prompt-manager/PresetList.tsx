import { Button } from "@/components/ui/button";
import { Plus, Search, Sparkles, Globe } from "lucide-react";
import { Preset } from "./types";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Badge } from "@/components/ui/badge";

interface PresetListProps {
  presets: Preset[];
  selectedPresetId: number | null;
  onSelect: (preset: Preset) => void;
  onCreate: () => void;
}

export function PresetList({
  presets,
  selectedPresetId,
  onSelect,
  onCreate,
}: PresetListProps) {
  const getTypeIcon = (type: string) => {
    switch (type) {
      case "generation":
        return <Sparkles className="h-3 w-3 text-purple-500" />;
      case "search":
        return <Search className="h-3 w-3 text-blue-500" />;
      default:
        return <Globe className="h-3 w-3 text-gray-500" />;
    }
  };

  return (
    <div className="w-1/3 min-w-[250px] flex flex-col gap-4 border-r pr-4">
      <div className="flex items-center justify-between">
        <h2 className="text-xl font-bold">Presets</h2>
        <Button size="sm" onClick={onCreate}>
          <Plus className="h-4 w-4" />
        </Button>
      </div>
      <ScrollArea className="flex-1 -mr-2 pr-2">
        <div className="space-y-2">
          {presets.map((preset) => (
            <div
              key={preset.id}
              className={`p-3 rounded-md cursor-pointer border transition-colors ${
                selectedPresetId === preset.id
                  ? "bg-accent border-primary/30"
                  : "hover:bg-muted bg-card"
              }`}
              onClick={() => onSelect(preset)}
            >
              <div className="flex items-center justify-between mb-1">
                <div className="font-medium text-sm truncate flex items-center gap-2">
                  {getTypeIcon(preset.preset_type)}
                  {preset.name}
                </div>
              </div>
              <div className="text-xs text-muted-foreground line-clamp-2">
                {preset.description || "No description"}
              </div>
              <div className="mt-2 flex gap-1">
                <Badge variant="outline" className="text-[10px] h-4 px-1">
                  {preset.preset_type}
                </Badge>
                {preset.prompt_id && (
                  <Badge variant="secondary" className="text-[10px] h-4 px-1">
                    LLM Linked
                  </Badge>
                )}
              </div>
            </div>
          ))}
        </div>
      </ScrollArea>
    </div>
  );
}
