import { useState, useEffect } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Slider } from "@/components/ui/slider";
import {
  Filter,
  Zap,
  Activity,
  Sun,
  Gauge,
  Music2,
  KeyRound,
  Loader2,
} from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Separator } from "@/components/ui/separator";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { MultiSelect } from "@/components/ui/multi-select";
import { FilterState } from "./types";
import { INITIAL_FILTERS, KEY_OPTIONS } from "./constants";
import { presetsService, Preset } from "@/services/presets";
import { genreService } from "@/services/genres";

interface FilterDialogProps {
  isOpen: boolean;
  onOpenChange: (open: boolean) => void;
  currentFilters: FilterState;
  currentPreset: string;
  onApply: (filters: FilterState, presetName: string) => void;
}

export function FilterDialog({
  isOpen,
  onOpenChange,
  currentFilters,
  currentPreset,
  onApply,
}: FilterDialogProps) {
  const [localFilters, setLocalFilters] = useState<FilterState>(currentFilters);
  const [localPreset, setLocalPreset] = useState<string>(currentPreset);

  // APIから取得したプリセットリスト
  const [presets, setPresets] = useState<Preset[]>([]);
  const [isLoadingPresets, setIsLoadingPresets] = useState(false);
  const [availableGenres, setAvailableGenres] = useState<string[]>([]);

  useEffect(() => {
    if (isOpen) {
      setLocalFilters(currentFilters);
      setLocalPreset(currentPreset);
      fetchPresets();
      fetchGenres();
    }
  }, [isOpen, currentFilters, currentPreset]);

  const fetchGenres = async () => {
    if (availableGenres.length > 0) return;
    try {
      const genres = await genreService.getAllGenres();
      setAvailableGenres(genres);
    } catch (error) {
      console.error("Failed to load genres", error);
    }
  };

  const fetchPresets = async () => {
    // 既に取得済みならスキップ
    if (presets.length > 0) return;

    setIsLoadingPresets(true);
    try {
      const data = await presetsService.getAll("search");
      setPresets(data);
    } catch (error) {
      console.error("Failed to load presets", error);
    } finally {
      setIsLoadingPresets(false);
    }
  };

  const handlePresetChange = (val: string) => {
    setLocalPreset(val);
    if (val === "custom") return;

    const selectedPreset = presets.find((p) => p.name === val);

    if (selectedPreset) {
      setLocalFilters((prev) => ({
        ...prev,
        vibePrompt: selectedPreset.prompt_content || null,
      }));
    }
  };

  const handleApply = () => {
    onApply(localFilters, localPreset);
  };

  return (
    <Dialog open={isOpen} onOpenChange={onOpenChange}>
      <DialogTrigger asChild>
        <Button
          variant={
            JSON.stringify(currentFilters) !== JSON.stringify(INITIAL_FILTERS)
              ? "secondary"
              : "outline"
          }
          className="gap-2"
        >
          <Filter className="h-4 w-4" />
          Mood & Filters
        </Button>
      </DialogTrigger>
      <DialogContent className="sm:max-w-[500px] max-h-[85vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Music2 className="h-5 w-5 text-primary" />
            Smart Vibe Search
          </DialogTitle>
          <DialogDescription>
            LLM解析データを活用し、DJの現場感覚で選曲します。
          </DialogDescription>
        </DialogHeader>
        
        <div className="grid gap-4 py-4">
          {/* Preset Selector */}
          <div className="bg-muted/50 p-3 rounded-md border border-border/50">
            <Label className="text-xs font-semibold mb-2 block text-foreground/80">
              シーン / 雰囲気プリセット
            </Label>
            <Select value={localPreset} onValueChange={handlePresetChange}>
              <SelectTrigger className="bg-background">
                <SelectValue placeholder="シーンを選択..." />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="custom">カスタム設定 (手動)</SelectItem>
                {isLoadingPresets ? (
                  <div className="p-2 flex justify-center text-muted-foreground">
                    <Loader2 className="h-4 w-4 animate-spin" />
                  </div>
                ) : (
                  presets.map((preset) => (
                    <SelectItem key={preset.id} value={preset.name}>
                      {preset.name}
                    </SelectItem>
                  ))
                )}
              </SelectContent>
            </Select>
            {/* Description Display */}
            {localPreset !== "custom" && (
              <p className="text-xs text-muted-foreground mt-2 px-1">
                {presets.find((p) => p.name === localPreset)?.description}
              </p>
            )}
          </div>

          {/* Vibe Prompt Input */}
          <div className="space-y-2">
            <Label className="text-xs font-semibold">Vibe Prompt (AI Search)</Label>
            <Textarea
              placeholder="Describe the vibe (e.g. 'Dark industrial techno for peak time')"
              value={localFilters.vibePrompt || ""}
              onChange={(e) => {
                setLocalFilters({ ...localFilters, vibePrompt: e.target.value });
                setLocalPreset("custom");
              }}
              className="h-20 text-xs resize-none"
            />
          </div>

          <Separator />

          {/* Advanced Sliders - Only show when in Custom mode */}
          {localPreset === "custom" && (
            <div className="grid gap-6 px-1 animate-in fade-in slide-in-from-top-2 duration-300">
              {/* Energy */}
              <div className="space-y-3">
                <div className="flex justify-between items-center">
                  <Label className="flex items-center gap-2 text-xs font-semibold">
                    <Zap className="h-3.5 w-3.5 text-orange-500" />
                    Energy (激しさ)
                  </Label>
                  <span className="text-xs text-muted-foreground font-mono bg-muted px-1.5 py-0.5 rounded">
                    {localFilters.minEnergy.toFixed(1)} -{" "}
                    {localFilters.maxEnergy.toFixed(1)}
                  </span>
                </div>
                <Slider
                  defaultValue={[0, 1]}
                  value={[localFilters.minEnergy, localFilters.maxEnergy]}
                  max={1}
                  step={0.05}
                  minStepsBetweenThumbs={0.1}
                  onValueChange={(val) => {
                    setLocalFilters({
                      ...localFilters,
                      minEnergy: val[0],
                      maxEnergy: val[1],
                    });
                    setLocalPreset("custom");
                  }}
                  className="[&_.range]:bg-orange-500"
                />
              </div>

              {/* Danceability */}
              <div className="space-y-3">
                <div className="flex justify-between items-center">
                  <Label className="flex items-center gap-2 text-xs font-semibold">
                    <Activity className="h-3.5 w-3.5 text-blue-500" />
                    Danceability (踊りやすさ)
                  </Label>
                  <span className="text-xs text-muted-foreground font-mono bg-muted px-1.5 py-0.5 rounded">
                    {localFilters.minDanceability.toFixed(1)} -{" "}
                    {localFilters.maxDanceability.toFixed(1)}
                  </span>
                </div>
                <Slider
                  defaultValue={[0, 1]}
                  value={[
                    localFilters.minDanceability,
                    localFilters.maxDanceability,
                  ]}
                  max={1}
                  step={0.05}
                  minStepsBetweenThumbs={0.1}
                  onValueChange={(val) => {
                    setLocalFilters({
                      ...localFilters,
                      minDanceability: val[0],
                      maxDanceability: val[1],
                    });
                    setLocalPreset("custom");
                  }}
                  className="[&_.range]:bg-blue-500"
                />
              </div>

              {/* Brightness */}
              <div className="space-y-3">
                <div className="flex justify-between items-center">
                  <Label className="flex items-center gap-2 text-xs font-semibold">
                    <Sun className="h-3.5 w-3.5 text-yellow-500" />
                    Brightness (音色: 暗⇔明)
                  </Label>
                  <span className="text-xs text-muted-foreground font-mono bg-muted px-1.5 py-0.5 rounded">
                    {localFilters.minBrightness.toFixed(1)} -{" "}
                    {localFilters.maxBrightness.toFixed(1)}
                  </span>
                </div>
                <Slider
                  defaultValue={[0, 1]}
                  value={[localFilters.minBrightness, localFilters.maxBrightness]}
                  max={1}
                  step={0.05}
                  minStepsBetweenThumbs={0.1}
                  onValueChange={(val) => {
                    setLocalFilters({
                      ...localFilters,
                      minBrightness: val[0],
                      maxBrightness: val[1],
                    });
                    setLocalPreset("custom");
                  }}
                  className="[&_.range]:bg-yellow-500"
                />
              </div>

              <Separator />

              {/* BPM & Key */}
              <div className="grid grid-cols-2 gap-4">
                {/* Key Selector */}
                <div className="space-y-2">
                  <Label className="flex items-center gap-2 text-xs font-semibold">
                    <KeyRound className="h-3.5 w-3.5 text-green-500" /> Key /
                    Scale
                  </Label>
                  <Select
                    value={localFilters.key || "all"}
                    onValueChange={(val) =>
                      setLocalFilters({
                        ...localFilters,
                        key: val === "all" ? "" : val,
                      })
                    }
                  >
                    <SelectTrigger className="h-8 text-xs">
                      <SelectValue placeholder="All Keys" />
                    </SelectTrigger>
                    <SelectContent className="max-h-[200px]">
                      <SelectItem value="all">All Keys</SelectItem>
                      {KEY_OPTIONS.map((k) => (
                        <SelectItem key={k.value} value={k.value}>
                          {k.label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>

                {/* BPM */}
                <div className="space-y-2">
                  <Label className="flex items-center gap-2 text-xs font-semibold">
                    <Gauge className="h-3.5 w-3.5 text-purple-500" /> BPM
                  </Label>
                  <div className="flex gap-2">
                    <Input
                      type="number"
                      placeholder="Target"
                      value={localFilters.bpm || ""}
                      onChange={(e) =>
                        setLocalFilters({
                          ...localFilters,
                          bpm: parseFloat(e.target.value) || null,
                        })
                      }
                      className="h-8 text-xs px-2"
                    />
                    <div className="flex items-center gap-1 w-16 shrink-0 relative">
                      <span className="text-xs text-muted-foreground absolute left-1">
                        ±
                      </span>
                      <Input
                        type="number"
                        placeholder="Rg"
                        value={localFilters.bpmRange}
                        onChange={(e) =>
                          setLocalFilters({
                            ...localFilters,
                            bpmRange: parseFloat(e.target.value),
                          })
                        }
                        className="h-8 text-xs pl-3 pr-1"
                      />
                    </div>
                  </div>
                </div>
              </div>

              {/* Genre Selector */}
              <div className="space-y-2">
                <Label className="flex items-center gap-2 text-xs font-semibold">
                  <Music2 className="h-3.5 w-3.5 text-pink-500" /> Genres
                </Label>
                <MultiSelect
                  options={availableGenres.map((g) => ({ label: g, value: g }))}
                  selected={localFilters.genres || []}
                  onChange={(selected) =>
                    setLocalFilters({ ...localFilters, genres: selected })
                  }
                  placeholder="Select genres..."
                  creatable={true}
                  customPrefix="expand:"
                  createLabel="Expand Search"
                />
              </div>
            </div>
          )}
        </div>

        <DialogFooter className="flex justify-between sm:justify-between">
          <Button
            variant="ghost"
            size="sm"
            onClick={() => {
              setLocalFilters(INITIAL_FILTERS);
              setLocalPreset("custom");
            }}
            className="text-muted-foreground hover:text-foreground"
          >
            リセット
          </Button>
          <Button size="sm" onClick={handleApply}>
            フィルター適用
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
