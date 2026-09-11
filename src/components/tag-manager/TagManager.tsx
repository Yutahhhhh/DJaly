import { ResizeHandle } from "@/components/play/ResizeHandle";
import { useState, useMemo, useEffect } from "react";
import { TagSidebar } from "./TagSidebar";
import { TagList } from "./TagList";
import { TagEditor } from "./TagEditor";
import { GenreManager } from "@/components/genre-manager/GenreManager";
import { useTrackSearch } from "@/components/music-library/useTrackSearch";
import { INITIAL_FILTERS } from "@/components/music-library";
import { usePlayerStore } from "@/stores/playerStore";

export type TagCategory = "track-info" | "lyrics" | "genre" | "subgenre";

export function TagManager() {
  const [activeCategory, setActiveCategory] = useState<TagCategory>("track-info");
  const [selectedItem, setSelectedItem] = useState<any>(null);
  const [statusFilter, setStatusFilter] = useState<string>("all");
  const { play } = usePlayerStore();

  const extraParams = useMemo(() => {
    const params: any = {};
    if (activeCategory === "track-info") {
      params.year_status = statusFilter;
    } else if (activeCategory === "lyrics") {
      params.lyrics_status = statusFilter;
    }
    return params;
  }, [activeCategory, statusFilter]);

  const trackSearch = useTrackSearch({ limit: 50, extraParams });

  // Reset filters when category changes
  useEffect(() => {
    trackSearch.setFilters(INITIAL_FILTERS);
    trackSearch.setQuery("");
    setStatusFilter("all");
  }, [activeCategory]);

  // Genre/Subgenre Mode: Use the original GenreManager component (Tabs UI)
  if (activeCategory === "genre" || activeCategory === "subgenre") {
    return (
      <div data-resize-scope className="analysis-panels h-full flex overflow-hidden w-full bg-background border-t">
        <TagSidebar 
          activeCategory={activeCategory} 
          onSelectCategory={(cat) => {
            setActiveCategory(cat);
            setSelectedItem(null);
          }}
          trackSearch={trackSearch}
          extraParams={extraParams}
        />
        <ResizeHandle variable="--tag-sidebar" storageKey="plumdeck.width.tags.sidebar" label="タグ分類の幅" min={140} max={400} />
        <div className="flex-1 min-w-0 bg-background">
          <GenreManager mode={activeCategory} onPlay={play} />
        </div>
      </div>
    );
  }

  // Track Info / Lyrics Mode
  return (
    <div data-resize-scope className="analysis-panels h-full flex overflow-hidden w-full bg-background border-t">
      <TagSidebar 
        activeCategory={activeCategory} 
        onSelectCategory={(cat) => {
          setActiveCategory(cat);
          setSelectedItem(null);
        }}
        trackSearch={trackSearch}
        extraParams={extraParams}
      />
      
      <ResizeHandle variable="--tag-sidebar" storageKey="plumdeck.width.tags.sidebar" label="タグ分類の幅" min={140} max={400} />
      <TagList 
        category={activeCategory}
        onSelectItem={setSelectedItem}
        selectedItem={selectedItem}
        trackSearch={trackSearch}
        statusFilter={statusFilter}
        setStatusFilter={setStatusFilter}
      />
      
      <ResizeHandle variable="--tag-list" storageKey="plumdeck.width.tags.list" label="タグ一覧の幅" min={160} max={600} />
      <TagEditor 
        category={activeCategory}
        selectedItem={selectedItem}
      />
    </div>
  );
}
