import { useRef, useCallback } from "react";
import { TagCategory } from "./TagManager";
import { Track } from "@/types";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Search, Loader2, Filter, Sparkles, X } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import {
  FilterDialog,
} from "@/components/music-library";
import { TrackRow } from "@/components/track-row";

interface TagListProps {
  category: TagCategory;
  onSelectItem: (item: any) => void;
  selectedItem: any;
  trackSearch: any;
  statusFilter: string;
  setStatusFilter: (val: string) => void;
}

export function TagList({ category, onSelectItem, selectedItem, trackSearch, statusFilter, setStatusFilter }: TagListProps) {
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
  } = trackSearch;

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

  return (
    <div className="w-80 border-r bg-muted/10 flex flex-col h-full">
      <div className="p-4 border-b space-y-4">
        <div className="flex items-center justify-between">
          <h2 className="font-semibold">
            {category === "track-info" ? "Tracks" : "Lyrics"}
          </h2>
        </div>
        
        <div className="space-y-2">
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

            <Select value={statusFilter} onValueChange={setStatusFilter}>
                <SelectTrigger className="h-8 text-xs">
                    <SelectValue placeholder="Filter by status" />
                </SelectTrigger>
                <SelectContent>
                    <SelectItem value="all">All Tracks</SelectItem>
                    <SelectItem value="set">
                        {category === "track-info" ? "Has Year" : "Has Lyrics"}
                    </SelectItem>
                    <SelectItem value="unset">
                        {category === "track-info" ? "Missing Year" : "Missing Lyrics"}
                    </SelectItem>
                </SelectContent>
            </Select>
        </div>
      </div>

      <ScrollArea className="flex-1">
        <div className="p-2 space-y-1">
          {tracks.map((track: Track, index: number) => (
              <TrackRow
                key={track.id}
                track={track}
                viewType="list"
                isSelected={selectedItem?.id === track.id}
                onClick={() => onSelectItem({ ...track, label: track.title, type: "track" })}
                innerRef={index === tracks.length - 1 ? lastTrackElementRef : undefined}
              />
            ))
          }
          {loading && (
            <div className="flex justify-center p-4">
              <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
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
        enabledSections={["metadata"]}
        triggerLabel="Filter"
      />
    </div>
  );
}
