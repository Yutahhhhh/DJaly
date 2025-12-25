import { useState, useEffect } from "react";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Label } from "@/components/ui/label";
import { Slider } from "@/components/ui/slider";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  Loader2,
  Sparkles,
  Footprints,
  ArrowRight,
  Check,
} from "lucide-react";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { MultiSelect } from "@/components/ui/multi-select";
import { Track } from "@/types";
import { setlistsService } from "@/services/setlists";
import { presetsService, Preset } from "@/services/presets";
import { genreService } from "@/services/genres";
import { TrackRow } from "../TrackRow";
import { Badge } from "@/components/ui/badge";
import { DropZone } from "./DropZone";

interface AutoTabProps {
  currentSetlistTracks: Track[];
  onInjectTracks: (tracks: Track[], startId?: number, endId?: number) => void;
  bridgeState?: {
    start: Track | null;
    end: Track | null;
    setStart: (t: Track | null) => void;
    setEnd: (t: Track | null) => void;
  };
}

export function AutoTab({
  currentSetlistTracks,
  onInjectTracks,
  bridgeState,
}: AutoTabProps) {
  const [mode, setMode] = useState<"infinite" | "bridge">("infinite");

  // Results
  const [autoTracks, setAutoTracks] = useState<Track[]>([]);
  const [isAutoLoading, setIsAutoLoading] = useState(false);

  // Common Filters
  const [autoGenres, setAutoGenres] = useState<string[]>([]);
  const [autoSubgenres, setAutoSubgenres] = useState<string[]>([]);
  const [length, setLength] = useState(5);
  const [availableGenres, setAvailableGenres] = useState<string[]>([]);
  const [availableSubgenres, setAvailableSubgenres] = useState<string[]>([]);

  // Infinite Mode State
  const [presets, setPresets] = useState<Preset[]>([]);
  const [selectedPreset, setSelectedPreset] = useState<number | null>(null);

  // Bridge Mode State (Fallback if bridgeState not provided)
  const [localStart, setLocalStart] = useState<Track | null>(null);
  const [localEnd, setLocalEnd] = useState<Track | null>(null);

  const startTrack = bridgeState?.start ?? localStart;
  const endTrack = bridgeState?.end ?? localEnd;
  const setStartTrack = bridgeState?.setStart ?? setLocalStart;
  const setEndTrack = bridgeState?.setEnd ?? setLocalEnd;

  useEffect(() => {
    presetsService.getAll("generation", true).then((data) => {
      setPresets(data);
    });
    // Load available genres and subgenres
    genreService.getAllGenres().then(setAvailableGenres);
    genreService.getAllSubgenres().then(setAvailableSubgenres);
  }, []);

  // Bridge Mode: Default Start is last track if not set (optional convenience)
  useEffect(() => {
    if (mode === "bridge" && !startTrack && currentSetlistTracks.length > 0) {
      // Automatically suggest last track as start, but allow overwrite
      setStartTrack(currentSetlistTracks[currentSetlistTracks.length - 1]);
    }
  }, [mode, currentSetlistTracks]);

  const generateInfinite = async () => {
    if (!selectedPreset) return;
    setIsAutoLoading(true);
    try {
      const seedIds = currentSetlistTracks.slice(-3).map((t) => t.id);
      const data = await setlistsService.generateAuto(
        selectedPreset,
        length,
        seedIds.length > 0 ? seedIds : undefined,
        autoGenres.length > 0 ? autoGenres : undefined,
        autoSubgenres.length > 0 ? autoSubgenres : undefined
      );
      setAutoTracks(data);
    } catch (e) {
      console.error(e);
      alert("Generation failed.");
    } finally {
      setIsAutoLoading(false);
    }
  };

  const generateBridge = async () => {
    if (!startTrack || !endTrack) return;
    setIsAutoLoading(true);
    try {
      const data = await setlistsService.generatePath(
        startTrack.id,
        endTrack.id,
        length,
        autoGenres.length > 0 ? autoGenres : undefined,
        autoSubgenres.length > 0 ? autoSubgenres : undefined
      );
      // Remove the start track from result if it's already in setlist
      // Pathfinding usually returns [Start, ...Intermediates, End]
      // We want to display the intermediates + end (or just intermediates if user keeps end separate)
      // Usually "Bridge" means filling the gap. Let's filter out the start ID.
      const resultToShow = data.filter((t) => t.id !== startTrack.id);
      setAutoTracks(resultToShow);
    } catch (e) {
      console.error(e);
      alert(
        "Pathfinding failed. Try increasing the length or changing genres."
      );
    } finally {
      setIsAutoLoading(false);
    }
  };

  const handleApply = () => {
    const filteredAutoTracks = autoTracks.filter(
      (t) => !currentSetlistTracks.some((st) => st.id === t.id)
    );

    if (mode === "bridge" && startTrack) {
      // Bridgeモードの場合、StartとEndの間を埋めるのが目的なので、
      // 生成されたリストからEndトラックも除外して挿入する。
      // (Startトラックは generateBridge 時点で既に除外されている前提)
      // filteredAutoTracks で既にセットリスト内の曲は除外されているはずだが、念のため
      const tracksToInject = filteredAutoTracks.filter(
        (t) =>
          t.id !== startTrack.id && (endTrack ? t.id !== endTrack.id : true)
      );

      onInjectTracks(tracksToInject, startTrack.id, endTrack?.id);
    } else {
      // Infinite or others: Just add to end
      onInjectTracks(filteredAutoTracks);
    }
    setAutoTracks([]);
    // Reset logic if needed
    if (mode === "bridge") {
      setStartTrack(null);
      setEndTrack(null);
    }
  };

  return (
    <div className="flex-1 flex flex-col p-0 m-0 min-h-0 bg-background">
      <Tabs
        value={mode}
        onValueChange={(v) => setMode(v as any)}
        className="flex-1 flex flex-col min-h-0"
      >
        {/* Tab Header */}
        <div className="p-2 border-b bg-muted/20 shrink-0">
          <TabsList className="w-full grid grid-cols-2">
            <TabsTrigger value="infinite" className="text-xs gap-2">
              <Sparkles className="h-3 w-3" /> Infinite Flow
            </TabsTrigger>
            <TabsTrigger value="bridge" className="text-xs gap-2">
              <Footprints className="h-3 w-3" /> Bridge Mode
            </TabsTrigger>
          </TabsList>
        </div>

        {/* Controls Area */}
        <div className="p-4 border-b space-y-4 bg-muted/5 shrink-0">
          {/* Mode Specific Controls */}
          {mode === "infinite" ? (
            <div className="space-y-2">
              <Label className="text-xs font-semibold text-muted-foreground mb-2 block">
                Target Vibe (Pattern)
              </Label>
              <Select
                value={selectedPreset ? selectedPreset.toString() : ""}
                onValueChange={(val) => setSelectedPreset(Number(val))}
                disabled={presets.length === 0}
              >
                <SelectTrigger className="h-9 text-xs bg-background">
                  <SelectValue placeholder="Select a vibe..." />
                </SelectTrigger>
                <SelectContent>
                  {presets.map((p) => (
                    <SelectItem key={p.id} value={p.id.toString()}>
                      {p.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          ) : (
            <div className="space-y-3">
              <Label className="text-xs font-semibold text-muted-foreground block text-center">
                Drag & Drop from Setlist (Left)
              </Label>
              {/* Bridge Visualizer / Drop Zones */}
              <div className="flex items-center justify-between gap-2">
                {/* Start Drop Zone */}
                <DropZone
                  id="bridge-start"
                  label="START"
                  track={startTrack}
                />

                <ArrowRight className="h-4 w-4 text-muted-foreground/50 shrink-0" />

                {/* End Drop Zone */}
                <DropZone
                  id="bridge-end"
                  label="END"
                  track={endTrack}
                />
              </div>
            </div>
          )}

          {/* Common Filters */}
          <div className="grid grid-cols-2 gap-3 pt-2 border-t border-border/50">
            <div className="space-y-1">
              <Label className="text-[10px] font-semibold text-muted-foreground">
                Filter Genres
              </Label>
              <MultiSelect
                options={availableGenres.map((g) => ({ label: g, value: g }))}
                selected={autoGenres}
                onChange={setAutoGenres}
                placeholder="All Genres"
              />
            </div>
            <div className="space-y-1">
              <Label className="text-[10px] font-semibold text-muted-foreground">
                Filter Subgenres
              </Label>
              <MultiSelect
                options={availableSubgenres.map((s) => ({ label: s, value: s }))}
                selected={autoSubgenres}
                onChange={setAutoSubgenres}
                placeholder="All Subgenres"
              />
            </div>
          </div>

          <div className="grid grid-cols-1 gap-3">
            <div className="space-y-1">
              <div className="flex justify-between items-center">
                <Label className="text-[10px] font-semibold text-muted-foreground">
                  Count
                </Label>
                <span className="text-[10px] font-mono bg-muted px-1.5 rounded">
                  {length} tracks
                </span>
              </div>
              <Slider
                value={[length]}
                min={3}
                max={20}
                step={1}
                onValueChange={([v]) => setLength(v)}
                className="py-1"
              />
            </div>
          </div>

          {/* Generate Action */}
          <Button
            className="w-full gap-2 mt-2"
            disabled={
              isAutoLoading ||
              (mode === "infinite" && !selectedPreset) ||
              (mode === "bridge" && (!startTrack || !endTrack))
            }
            onClick={mode === "infinite" ? generateInfinite : generateBridge}
          >
            {isAutoLoading ? (
              <Loader2 className="animate-spin h-4 w-4" />
            ) : mode === "infinite" ? (
              <Sparkles className="h-4 w-4" />
            ) : (
              <Footprints className="h-4 w-4" />
            )}
            {mode === "infinite" ? "Generate Flow" : "Build Bridge"}
          </Button>
        </div>

        {/* Results Area */}
        <div className="flex-1 overflow-hidden flex flex-col bg-background">
          {autoTracks.length > 0 && (
            <div className="p-2 border-b bg-accent/20 flex justify-between items-center shrink-0 animate-in fade-in slide-in-from-top-1">
              <div className="flex items-center gap-2">
                <Badge
                  variant="secondary"
                  className="text-[10px] px-1.5 h-5 font-normal"
                >
                  {autoTracks.length} Recommended
                </Badge>
              </div>
              <Button
                size="sm"
                className="h-7 text-xs gap-1"
                onClick={handleApply}
              >
                <Check className="h-3 w-3" /> Apply to Setlist
              </Button>
            </div>
          )}

          <ScrollArea className="flex-1">
            <div className="pb-10">
              {autoTracks
                .filter(
                  (t) => !currentSetlistTracks.some((st) => st.id === t.id)
                )
                .map((t, idx) => (
                  <div
                    key={`auto-${t.id}-${idx}`}
                    className="relative group animate-in fade-in slide-in-from-bottom-2"
                    style={{ animationDelay: `${idx * 50}ms` }}
                  >
                    <TrackRow
                      id={`auto-${t.id}-${idx}`}
                      track={t}
                      type="LIBRARY_ITEM"
                      onAdd={() => onInjectTracks([t], startTrack?.id)}
                    />
                  </div>
                ))
              }

              {autoTracks.length === 0 && !isAutoLoading && (
                <div className="h-full flex flex-col items-center justify-center p-8 text-muted-foreground gap-3 opacity-50 min-h-[200px]">
                  {mode === "infinite" ? (
                    <>
                      <Sparkles className="h-8 w-8" />
                      <div className="text-center text-xs">
                        Select a Vibe Preset to
                        <br />
                        generate an infinite mix.
                      </div>
                    </>
                  ) : (
                    <>
                      <Footprints className="h-8 w-8" />
                      <div className="text-center text-xs">
                        Drag & Drop Start/End tracks
                        <br />
                        to find the perfect bridge.
                      </div>
                    </>
                  )}
                </div>
              )}

              {isAutoLoading && autoTracks.length === 0 && (
                <div className="h-full flex flex-col items-center justify-center p-8 min-h-[200px]">
                  <Loader2 className="h-8 w-8 animate-spin text-primary/50" />
                  <p className="text-xs text-muted-foreground mt-2">
                    AI is thinking...
                  </p>
                </div>
              )}
            </div>
          </ScrollArea>
        </div>
      </Tabs>
    </div>
  );
}
