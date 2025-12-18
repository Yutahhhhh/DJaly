import { Label } from "@/components/ui/label";
import { Slider } from "@/components/ui/slider";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { KEY_OPTIONS } from "@/components/music-library/constants";
import { Separator } from "@/components/ui/separator";

interface FilterEditorProps {
  filters: any;
  onChange: (newFilters: any) => void;
  mode: "search" | "generation" | "all";
}

export function FilterEditor({ filters, onChange, mode }: FilterEditorProps) {
  const updateFilter = (key: string, value: any) => {
    onChange({ ...filters, [key]: value });
  };

  const getVal = (key: string, def: any) => filters[key] ?? def;

  // generationモードの場合はフィルタ設定をシンプルにする、などの制御も可能だが
  // 今回は共通のUIで編集可能にする。

  return (
    <div className="space-y-6 border p-4 rounded-md bg-card">
      <h3 className="font-semibold text-sm text-muted-foreground mb-4">
        JSON Filter Configuration
      </h3>

      {/* BPM */}
      <div className="grid grid-cols-2 gap-4">
        <div className="space-y-2">
          <Label>Target BPM</Label>
          <Input
            type="number"
            value={getVal("bpm", "")}
            onChange={(e) => updateFilter("bpm", parseFloat(e.target.value))}
            placeholder="e.g. 128"
          />
        </div>
        <div className="space-y-2">
          <Label>Key</Label>
          <Select
            value={getVal("key", "")}
            onValueChange={(val) => updateFilter("key", val)}
          >
            <SelectTrigger>
              <SelectValue placeholder="Select Key" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">Any Key</SelectItem>
              {KEY_OPTIONS.map((k) => (
                <SelectItem key={k.value} value={k.value}>
                  {k.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </div>

      <Separator />

      {/* Ranges */}
      <div className="space-y-4">
        {/* Energy */}
        <div className="space-y-3">
          <div className="flex justify-between text-sm">
            <Label>Energy Range</Label>
            <span className="text-muted-foreground">
              {getVal("minEnergy", 0)} - {getVal("maxEnergy", 1)}
            </span>
          </div>
          <Slider
            value={[getVal("minEnergy", 0), getVal("maxEnergy", 1)]}
            min={0}
            max={1}
            step={0.05}
            onValueChange={(val) => {
              updateFilter("minEnergy", val[0]);
              updateFilter("maxEnergy", val[1]);
            }}
          />
        </div>

        {/* Danceability */}
        <div className="space-y-3">
          <div className="flex justify-between text-sm">
            <Label>Danceability Range</Label>
            <span className="text-muted-foreground">
              {getVal("minDanceability", 0)} - {getVal("maxDanceability", 1)}
            </span>
          </div>
          <Slider
            value={[getVal("minDanceability", 0), getVal("maxDanceability", 1)]}
            min={0}
            max={1}
            step={0.05}
            onValueChange={(val) => {
              updateFilter("minDanceability", val[0]);
              updateFilter("maxDanceability", val[1]);
            }}
          />
        </div>

        {/* Brightness */}
        <div className="space-y-3">
          <div className="flex justify-between text-sm">
            <Label>Brightness Range</Label>
            <span className="text-muted-foreground">
              {getVal("minBrightness", 0)} - {getVal("maxBrightness", 1)}
            </span>
          </div>
          <Slider
            value={[getVal("minBrightness", 0), getVal("maxBrightness", 1)]}
            min={0}
            max={1}
            step={0.05}
            onValueChange={(val) => {
              updateFilter("minBrightness", val[0]);
              updateFilter("maxBrightness", val[1]);
            }}
          />
        </div>
      </div>
    </div>
  );
}
