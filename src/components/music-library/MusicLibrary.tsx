import { useState, useRef, useCallback } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Sparkles, Search, X } from "lucide-react";
import { Track } from "@/types";
import { Badge } from "@/components/ui/badge";
import { FilterDialog } from "./FilterDialog";
import { TrackList } from "./TrackList";
import { FilterState } from "./types";
import { ingestService } from "@/services/ingest";
import { useTrackSearch } from "./useTrackSearch";
import { LIMIT } from "./constants";

interface MusicLibraryProps {
  isPlayerLoading?: boolean;
}

export function MusicLibrary({
  isPlayerLoading,
}: MusicLibraryProps) {
  const [analyzingId, setAnalyzingId] = useState<number | null>(null);

  const {
    query,
    setQuery,
    tracks,
    loading,
    filters,
    currentPreset,
    isFilterOpen,
    setIsFilterOpen,
    applyFilters,
    clearAllFilters,
    loadMore,
    hasMore,
    activeFilterCount,
    setTracks,
    search,
  } = useTrackSearch({ limit: LIMIT });

  const observer = useRef<IntersectionObserver | null>(null);
  const lastTrackElementRef = useCallback(
    (node: HTMLTableRowElement | null) => {
      if (loading) return;
      if (observer.current) observer.current.disconnect();
      observer.current = new IntersectionObserver((entries) => {
        if (entries[0].isIntersecting && hasMore) {
          loadMore();
        }
      });
      if (node) observer.current.observe(node);
    },
    [loading, hasMore, loadMore]
  );

  const clearFilter = (key: keyof FilterState) => {
    const newFilters = { ...filters };
    // Reset specific fields to default
    if (key === "bpm") newFilters.bpm = null;
    else if (key === "key") newFilters.key = "";
    else if (key === "artist") newFilters.artist = "";
    else if (key === "album") newFilters.album = "";
    else if (key === "genres") newFilters.genres = [];
    else if (key === "subgenres") newFilters.subgenres = [];
    // Reset ranges to full
    else if (key.toString().includes("Energy")) {
      newFilters.minEnergy = 0.0;
      newFilters.maxEnergy = 1.0;
    } else if (key.toString().includes("Danceability")) {
      newFilters.minDanceability = 0.0;
      newFilters.maxDanceability = 1.0;
    } else if (key.toString().includes("Brightness")) {
      newFilters.minBrightness = 0.0;
      newFilters.maxBrightness = 1.0;
    }

    applyFilters(newFilters, "custom");
  };

  const handleAnalyze = async (track: Track) => {
    if (analyzingId) return;
    setAnalyzingId(track.id);

    try {
      await ingestService.ingest([track.filepath], true);
      // Refresh tracks to get updated analysis
      search(true);
    } catch (error) {
      console.error("Error calling analyze API", error);
    } finally {
      setAnalyzingId(null);
    }
  };

  const handleTrackUpdate = (trackId: number, updates: Partial<Track>) => {
    setTracks((prev) =>
      prev.map((t) => (t.id === trackId ? { ...t, ...updates } : t))
    );
  };

  // Helper to count active filters for display logic (hook provides total count, but we need specific checks for badges)
  const isFeatureActive = (min: number, max: number) => min > 0 || max < 1;

  return (
    <div className="h-full flex flex-col p-4 gap-4">
      <div className="flex flex-col gap-4">
        <div className="flex items-center justify-between">
          <h2 className="text-2xl font-bold flex items-center gap-2">
            <Sparkles className="h-6 w-6 text-purple-500" />
            Music Library
          </h2>
          <div className="text-sm text-muted-foreground">
            {tracks.length} tracks loaded
          </div>
        </div>

        {/* Search & Filter Bar */}
        <div className="flex items-center gap-2">
          <div className="relative flex-1">
            <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
            <Input
              placeholder="Search by Title, Artist or Tags..."
              className="pl-9"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
            {query && (
              <button
                className="absolute right-2.5 top-2.5 text-muted-foreground hover:text-foreground"
                onClick={() => setQuery("")}
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

        {/* Active Filters Display */}
        {activeFilterCount > 0 && (
          <div className="flex flex-wrap gap-2 items-center">
            <span className="text-xs text-muted-foreground mr-1">Active:</span>

            {currentPreset !== "custom" && (
              <Badge
                variant="outline"
                className="gap-1 border-purple-400 text-purple-500"
              >
                <Sparkles className="h-3 w-3" />
                Mood: {currentPreset.replace("_", " ").toUpperCase()}
              </Badge>
            )}

            {filters.bpm && (
              <Badge variant="secondary" className="gap-1">
                BPM: {filters.bpm}
                <X
                  className="h-3 w-3 cursor-pointer"
                  onClick={() => clearFilter("bpm")}
                />
              </Badge>
            )}
            {/* Key Badge */}
            {filters.key && (
              <Badge
                variant="secondary"
                className="gap-1 bg-green-100 text-green-800 hover:bg-green-200"
              >
                Key: {filters.key}
                <X
                  className="h-3 w-3 cursor-pointer"
                  onClick={() => clearFilter("key")}
                />
              </Badge>
            )}

            {/* Feature Badges */}
            {isFeatureActive(filters.minEnergy, filters.maxEnergy) && (
              <Badge variant="secondary" className="gap-1">
                Energy: {filters.minEnergy} - {filters.maxEnergy}
                <X
                  className="h-3 w-3 cursor-pointer"
                  onClick={() => clearFilter("minEnergy")}
                />
              </Badge>
            )}
            {isFeatureActive(filters.minBrightness, filters.maxBrightness) && (
              <Badge variant="secondary" className="gap-1">
                Bright: {filters.minBrightness} - {filters.maxBrightness}
                <X
                  className="h-3 w-3 cursor-pointer"
                  onClick={() => clearFilter("minBrightness")}
                />
              </Badge>
            )}

            <Button
              variant="ghost"
              size="sm"
              className="h-6 text-xs"
              onClick={clearAllFilters}
            >
              Clear All
            </Button>
          </div>
        )}
      </div>

      {/* Track List */}
      <TrackList
        tracks={tracks}
        isLoading={loading && tracks.length === 0}
        lastTrackElementRef={lastTrackElementRef}
        analyzingId={analyzingId}
        onAnalyze={handleAnalyze}
        disabled={isPlayerLoading}
        onTrackUpdate={handleTrackUpdate}
      />
    </div>
  );
}