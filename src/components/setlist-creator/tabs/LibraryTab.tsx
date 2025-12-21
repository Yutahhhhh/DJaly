import { useState, useEffect } from "react";
import { Input } from "@/components/ui/input";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Search, Loader2, Sparkles, Filter, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Track } from "@/types";
import { tracksService } from "@/services/tracks";
import { TrackRow } from "../TrackRow";
import {
  FilterDialog,
  FilterState,
  INITIAL_FILTERS,
  buildTrackSearchParams,
} from "@/components/music-library";

interface LibraryTabProps {
  onAddTrack: (track: Track) => void;
  onPlay: (track: Track) => void;
  currentTrackId?: number | null;
  currentSetlistTracks: Track[];
}

export function LibraryTab({
  onAddTrack,
  onPlay,
  currentTrackId,
  currentSetlistTracks,
}: LibraryTabProps) {
  const [query, setQuery] = useState("");
  const [tracks, setTracks] = useState<Track[]>([]);
  const [loading, setLoading] = useState(false);

  // Filter States
  const [filters, setFilters] = useState<FilterState>(INITIAL_FILTERS);
  const [currentPreset, setCurrentPreset] = useState("custom");
  const [isFilterOpen, setIsFilterOpen] = useState(false);

  useEffect(() => {
    const t = setTimeout(() => search(query, filters), 300);
    return () => clearTimeout(t);
  }, [query]);

  const search = async (currentTitle: string, currentFilters: FilterState) => {
    setLoading(true);
    try {
      const params = buildTrackSearchParams(currentTitle, currentFilters, 50);
      const data = await tracksService.getTracks(params);
      setTracks(data);
    } finally {
      setLoading(false);
    }
  };

  const applyFilters = (
    newFilters: FilterState,
    presetName: string = "custom"
  ) => {
    setFilters(newFilters);
    setCurrentPreset(presetName);
    setIsFilterOpen(false);
    search(query, newFilters);
  };

  const clearAllFilters = () => {
    setQuery("");
    applyFilters(INITIAL_FILTERS, "custom");
  };

  const activeFilterCount = Object.keys(filters).filter((k) => {
    const key = k as keyof FilterState;
    if (key === "bpmRange") return false;
    if (key === "minEnergy" || key === "maxEnergy")
      return filters.minEnergy > 0 || filters.maxEnergy < 1;
    if (key === "minDanceability" || key === "maxDanceability")
      return filters.minDanceability > 0 || filters.maxDanceability < 1;
    if (key === "minBrightness" || key === "maxBrightness")
      return filters.minBrightness > 0 || filters.maxBrightness < 1;
    
    const val = filters[key];
    if (Array.isArray(val)) return val.length > 0;
    return val !== null && val !== "" && val !== 0;
  }).length;

  return (
    <div className="flex-1 flex flex-col min-h-0 bg-background">
      <div className="p-2 border-b space-y-2">
        <div className="flex gap-2">
          <div className="relative flex-1">
            <Search className="absolute left-2 top-2.5 h-4 w-4 text-muted-foreground" />
            <Input
              className="pl-8 h-9 text-xs"
              placeholder="Search tracks..."
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
          </div>
          <Button
            variant={
              filters.vibePrompt || activeFilterCount > 0
                ? "default"
                : "outline"
            }
            size="icon"
            className="h-9 w-9 shrink-0"
            onClick={() => setIsFilterOpen(true)}
          >
            {filters.vibePrompt ? (
              <Sparkles className="h-4 w-4" />
            ) : (
              <Filter className="h-4 w-4" />
            )}
          </Button>
          {(filters.vibePrompt || activeFilterCount > 0) && (
             <Button
                variant="ghost"
                size="icon"
                className="h-9 w-9 shrink-0"
                onClick={clearAllFilters}
             >
                <X className="h-4 w-4" />
             </Button>
          )}
        </div>
        
        {filters.vibePrompt && (
            <div className="flex items-center gap-2">
                <Badge variant="secondary" className="text-[10px] truncate max-w-full">
                    <Sparkles className="h-3 w-3 mr-1 text-purple-500" />
                    {filters.vibePrompt}
                </Badge>
            </div>
        )}
      </div>
      <ScrollArea className="flex-1">
        {loading ? (
          <div className="p-8 flex justify-center">
            <Loader2 className="animate-spin h-6 w-6 opacity-20" />
          </div>
        ) : (
          <div className="p-2 space-y-1">
            {tracks
              .filter((t) => !currentSetlistTracks.some((st) => st.id === t.id))
              .map((t) => (
                <TrackRow
                  key={`lib-${t.id}`}
                  id={`lib-${t.id}`}
                  track={t}
                  type="LIBRARY_ITEM"
                  isPlaying={currentTrackId === t.id}
                  onPlay={() => onPlay(t)}
                  onAdd={() => onAddTrack(t)}
                />
              ))}
          </div>
        )}
      </ScrollArea>

      <FilterDialog
        isOpen={isFilterOpen}
        onOpenChange={setIsFilterOpen}
        currentFilters={filters}
        currentPreset={currentPreset}
        onApply={applyFilters}
      />
    </div>
  );
}
