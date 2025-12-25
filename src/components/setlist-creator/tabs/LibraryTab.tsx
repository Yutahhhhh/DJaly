import {  useRef, useCallback } from "react";
import { Input } from "@/components/ui/input";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Search, Loader2, Sparkles, Filter, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Track } from "@/types";
import { TrackRow } from "../TrackRow";
import {
  FilterDialog,
} from "@/components/music-library";
import { useTrackSearch } from "@/components/music-library/useTrackSearch";

interface LibraryTabProps {
  onAddTrack: (track: Track) => void;
  currentSetlistTracks: Track[];
}

export function LibraryTab({
  onAddTrack,
  currentSetlistTracks,
}: LibraryTabProps) {
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
  } = useTrackSearch();

  const observer = useRef<IntersectionObserver | null>(null);
  const lastTrackElementRef = useCallback(
    (node: HTMLDivElement | null) => {
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

  const filteredTracks = tracks.filter(
    (t) => !currentSetlistTracks.some((st) => st.id === t.id)
  );

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
        <div className="p-2 space-y-1">
          {filteredTracks.map((t, index) => (
            <TrackRow
              key={`lib-${t.id}`}
              id={`lib-${t.id}`}
              track={t}
              type="LIBRARY_ITEM"
              onAdd={() => onAddTrack(t)}
              innerRef={
                index === filteredTracks.length - 1
                  ? lastTrackElementRef
                  : undefined
              }
            />
          ))}
          {loading && (
            <div className="p-4 flex justify-center">
              <Loader2 className="animate-spin h-6 w-6 opacity-20" />
            </div>
          )}
        </div>
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
