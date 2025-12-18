import { useState, useEffect, useRef, useCallback } from "react";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  Loader2,
  Search,
  Sparkles,
  X,
} from "lucide-react";
import { Track } from "@/types";
import { tracksService } from "@/services/tracks";
import { FilterDialog } from "@/components/music-library/FilterDialog";
import { FilterState } from "@/components/music-library/types";
import { INITIAL_FILTERS } from "@/components/music-library/constants";
import { Badge } from "@/components/ui/badge";
import { buildTrackSearchParams } from "../utils";
import { TrackRow } from "../TrackRow";

interface LibraryTabProps {
  onAddTrack: (track: Track) => void;
  onPlay: (track: Track) => void;
  currentTrackId?: number | null;
}

export function LibraryTab({ onAddTrack, onPlay, currentTrackId }: LibraryTabProps) {
  const [searchQuery, setSearchQuery] = useState("");
  const [libraryTracks, setLibraryTracks] = useState<Track[]>([]);
  const [isLibraryLoading, setIsLibraryLoading] = useState(false);
  const [filters, setFilters] = useState<FilterState>(INITIAL_FILTERS);
  const [currentPreset, setCurrentPreset] = useState("custom");
  const [isFilterOpen, setIsFilterOpen] = useState(false);
  const searchTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const fetchLibrary = useCallback(
    async (
      query: string = searchQuery,
      currentFilters: FilterState = filters
    ) => {
      setIsLibraryLoading(true);
      try {
        const params = buildTrackSearchParams(query, currentFilters);
        const data = await tracksService.getTracks(params);
        setLibraryTracks(data);
      } finally {
        setIsLibraryLoading(false);
      }
    },
    [searchQuery, filters]
  );

  // Initial load
  useEffect(() => {
    if (libraryTracks.length === 0) fetchLibrary();
  }, []);

  // Debounced Search
  const handleSearchChange = (val: string) => {
    setSearchQuery(val);
    if (searchTimeoutRef.current) clearTimeout(searchTimeoutRef.current);
    searchTimeoutRef.current = setTimeout(() => {
      fetchLibrary(val, filters);
    }, 500);
  };

  const applyFilters = (newFilters: FilterState, presetName: string) => {
    setFilters(newFilters);
    setCurrentPreset(presetName);
    setIsFilterOpen(false);
    fetchLibrary(searchQuery, newFilters);
  };

  const activeFilterCount = [
    filters.bpm,
    filters.key,
    filters.artist,
    filters.genres?.length,
    filters.minEnergy > 0 || filters.maxEnergy < 1,
    filters.vibePrompt,
  ].filter(Boolean).length;

  return (
    <div className="flex-1 flex flex-col p-0 m-0 min-h-0">
      <div className="p-2 border-b space-y-2 shrink-0 bg-background">
        <div className="flex items-center gap-2">
          <div className="relative flex-1">
            <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
            <Input
              placeholder="Search..."
              className="pl-8 h-9 text-sm"
              value={searchQuery}
              onChange={(e) => handleSearchChange(e.target.value)}
            />
            {searchQuery && (
              <button
                className="absolute right-2.5 top-2.5 text-muted-foreground hover:text-foreground"
                onClick={() => handleSearchChange("")}
              >
                <X className="h-4 w-4" />
              </button>
            )}
          </div>
          <FilterDialog
            isOpen={isFilterOpen}
            onOpenChange={setIsFilterOpen}
            currentFilters={filters}
            currentPreset={currentPreset}
            onApply={applyFilters}
          />
        </div>
        {/* Active Filter Indicators */}
        {activeFilterCount > 0 && (
          <div className="flex flex-wrap gap-1 px-1">
            {filters.vibePrompt && (
              <Badge variant="default" className="text-[10px] h-5 px-1 bg-purple-600 hover:bg-purple-700">
                <Sparkles className="h-3 w-3 mr-1" />
                AI Vibe
              </Badge>
            )}
            {filters.bpm && (
              <Badge variant="secondary" className="text-[10px] h-5 px-1">
                BPM: {filters.bpm}
              </Badge>
            )}
            {filters.key && (
              <Badge variant="secondary" className="text-[10px] h-5 px-1">
                Key: {filters.key}
              </Badge>
            )}
            <Button
              variant="ghost"
              size="sm"
              className="h-5 text-[10px] px-1 text-muted-foreground"
              onClick={() => applyFilters(INITIAL_FILTERS, "custom")}
            >
              Clear
            </Button>
          </div>
        )}
      </div>

      <div className="flex-1 overflow-hidden">
        <ScrollArea className="h-full bg-background">
          {isLibraryLoading ? (
            <div className="flex justify-center p-8">
              <Loader2 className="animate-spin h-6 w-6 text-muted-foreground" />
            </div>
          ) : libraryTracks.length > 0 ? (
            <div className="pb-10">
              {libraryTracks.map((t) => (
                <TrackRow
                  key={t.id}
                  track={t}
                  currentTrackId={currentTrackId}
                  onPlay={onPlay}
                  onAddTrack={onAddTrack}
                />
              ))}
            </div>
          ) : (
            <div className="text-center p-8 text-muted-foreground text-sm">
              No tracks found.
            </div>
          )}
        </ScrollArea>
      </div>
    </div>
  );
}
