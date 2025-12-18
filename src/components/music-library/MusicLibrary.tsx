import { useState, useEffect, useRef, useCallback } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Sparkles, Search, X } from "lucide-react";
import { Track } from "@/types";
import { Badge } from "@/components/ui/badge";
import { FilterDialog } from "./FilterDialog";
import { TrackList } from "./TrackList";
import { FilterState } from "./types";
import { INITIAL_FILTERS, LIMIT } from "./constants";
import { tracksService } from "@/services/tracks";
import { ingestService } from "@/services/ingest";

interface MusicLibraryProps {
  onPlay: (track: Track) => void;
  currentTrackId?: number | null;
  isPlayerLoading?: boolean;
}

export function MusicLibrary({
  onPlay,
  currentTrackId,
  isPlayerLoading,
}: MusicLibraryProps) {
  const [tracks, setTracks] = useState<Track[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [analyzingId, setAnalyzingId] = useState<number | null>(null);
  const [hasMore, setHasMore] = useState(true);
  const [offset, setOffset] = useState(0);

  // Search States
  const [titleQuery, setTitleQuery] = useState("");
  const [filters, setFilters] = useState<FilterState>(INITIAL_FILTERS);
  const [currentPreset, setCurrentPreset] = useState("custom");

  // Popover open state
  const [isFilterOpen, setIsFilterOpen] = useState(false);

  // Debounce timer
  const searchTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const observer = useRef<IntersectionObserver | null>(null);
  const lastTrackElementRef = useCallback(
    (node: HTMLTableRowElement | null) => {
      if (isLoading) return;
      if (observer.current) observer.current.disconnect();
      observer.current = new IntersectionObserver((entries) => {
        if (entries[0].isIntersecting && hasMore) {
          setOffset((prevOffset) => prevOffset + LIMIT);
        }
      });
      if (node) observer.current.observe(node);
    },
    [isLoading, hasMore]
  );

  useEffect(() => {
    fetchTracks();
  }, [offset]);

  // Handle Main Title Search with Debounce
  const handleTitleSearch = (val: string) => {
    setTitleQuery(val);
    if (searchTimeoutRef.current) clearTimeout(searchTimeoutRef.current);

    searchTimeoutRef.current = setTimeout(() => {
      setOffset(0);
      fetchTracks(true, val, filters);
    }, 500);
  };

  // Apply Filters
  const applyFilters = (
    newFilters: FilterState,
    presetName: string = "custom"
  ) => {
    setFilters(newFilters);
    setCurrentPreset(presetName);
    setIsFilterOpen(false);
    setOffset(0);
    setTimeout(() => fetchTracks(true, titleQuery, newFilters), 0);
  };

  const clearFilter = (key: keyof FilterState) => {
    const newFilters = { ...filters };
    // Reset specific fields to default
    if (key === "bpm") newFilters.bpm = null;
    else if (key === "key") newFilters.key = "";
    else if (key === "artist") newFilters.artist = "";
    else if (key === "album") newFilters.album = "";
    else if (key === "genres") newFilters.genres = [];
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

  const clearAllFilters = () => {
    setTitleQuery("");
    applyFilters(INITIAL_FILTERS, "custom");
  };

  const fetchTracks = async (
    reset = false,
    currentTitle = titleQuery,
    currentFilters = filters
  ) => {
    setIsLoading(true);
    try {
      const currentOffset = reset ? 0 : offset;
      const params: Record<string, any> = {
        status: "all",
        limit: LIMIT.toString(),
        offset: currentOffset.toString(),
      };

      if (currentTitle) params["title"] = currentTitle;

      // Basic Filters
      if (currentFilters.bpm && currentFilters.bpm > 0) {
        params["bpm"] = currentFilters.bpm.toString();
        params["bpm_range"] = currentFilters.bpmRange.toString();
      }
      if (currentFilters.key) params["key"] = currentFilters.key;
      if (currentFilters.artist) params["artist"] = currentFilters.artist;
      if (currentFilters.album) params["album"] = currentFilters.album;
      if (currentFilters.genres && currentFilters.genres.length > 0) {
        params["genres"] = currentFilters.genres;
      }
      if (currentFilters.minDuration)
        params["min_duration"] = currentFilters.minDuration.toString();
      if (currentFilters.maxDuration)
        params["max_duration"] = currentFilters.maxDuration.toString();

      // Advanced Feature Filters (Only send if range is narrowed)
      if (currentFilters.minEnergy > 0)
        params["min_energy"] = currentFilters.minEnergy.toString();
      if (currentFilters.maxEnergy < 1)
        params["max_energy"] = currentFilters.maxEnergy.toString();

      if (currentFilters.minDanceability > 0)
        params["min_danceability"] = currentFilters.minDanceability.toString();
      if (currentFilters.maxDanceability < 1)
        params["max_danceability"] = currentFilters.maxDanceability.toString();

      if (currentFilters.minBrightness > 0)
        params["min_brightness"] = currentFilters.minBrightness.toString();
      if (currentFilters.maxBrightness < 1)
        params["max_brightness"] = currentFilters.maxBrightness.toString();

      // Vibe Search
      if (currentFilters.vibePrompt) {
        params["vibe_prompt"] = currentFilters.vibePrompt;
      }

      const response = await tracksService.getTracks(params);
      setTracks((prev) => {
        if (reset || currentOffset === 0) return response;

        // 重複排除ロジックを追加
        // IDが既に存在する場合は追加しないようにフィルタリング
        const existingIds = new Set(prev.map((t) => t.id));
        const uniqueNewTracks = response.filter((t) => !existingIds.has(t.id));

        return [...prev, ...uniqueNewTracks];
      });
      
      // Vibe Search (Preset) の場合はページングを無効化 (一貫性のため)
      // 通常の検索の場合はページングを有効化
      if (currentFilters.vibePrompt) {
        setHasMore(false);
      } else {
        setHasMore(response.length === LIMIT);
      }
    } catch (e) {
      console.error("Failed to fetch tracks", e);
    } finally {
      setIsLoading(false);
    }
  };

  const handleAnalyze = async (track: Track) => {
    if (analyzingId) return;
    setAnalyzingId(track.id);

    try {
      await ingestService.ingest([track.filepath], true);
      setOffset(0);
      fetchTracks(true);
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

  // Helper to count active filters
  const isFeatureActive = (min: number, max: number) => min > 0 || max < 1;
  const activeFilterCount = [
    filters.bpm,
    filters.key,
    filters.artist,
    filters.album,
    filters.genre,
    isFeatureActive(filters.minEnergy, filters.maxEnergy),
    isFeatureActive(filters.minDanceability, filters.maxDanceability),
    isFeatureActive(filters.minBrightness, filters.maxBrightness),
  ].filter(Boolean).length;

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
              value={titleQuery}
              onChange={(e) => handleTitleSearch(e.target.value)}
            />
            {titleQuery && (
              <button
                className="absolute right-2.5 top-2.5 text-muted-foreground hover:text-foreground"
                onClick={() => handleTitleSearch("")}
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
        isLoading={isLoading && tracks.length === 0}
        onPlay={onPlay}
        currentTrackId={currentTrackId}
        lastTrackElementRef={lastTrackElementRef}
        analyzingId={analyzingId}
        onAnalyze={handleAnalyze}
        disabled={isPlayerLoading}
        onTrackUpdate={handleTrackUpdate}
      />
    </div>
  );
}
