import { useState, useEffect, useCallback } from "react";
import { Track } from "@/types";
import { tracksService } from "@/services/tracks";
import { FilterState } from "./types";
import { INITIAL_FILTERS } from "./constants";
import { buildTrackSearchParams } from "./utils";

interface UseTrackSearchProps {
  initialFilters?: FilterState;
  limit?: number;
  extraParams?: Record<string, any>;
}

export function useTrackSearch({ initialFilters = INITIAL_FILTERS, limit = 50, extraParams = {} }: UseTrackSearchProps = {}) {
  const [query, setQuery] = useState("");
  const [tracks, setTracks] = useState<Track[]>([]);
  const [loading, setLoading] = useState(false);
  const [filters, setFilters] = useState<FilterState>(initialFilters);
  const [currentPreset, setCurrentPreset] = useState("custom");
  const [isFilterOpen, setIsFilterOpen] = useState(false);
  const [page, setPage] = useState(0);
  const [hasMore, setHasMore] = useState(true);

  const search = useCallback(async (resetPage = false) => {
    setLoading(true);
    try {
      const currentPage = resetPage ? 0 : page;
      const offset = currentPage * limit;
      
      const params = buildTrackSearchParams(query, filters, limit, offset);
      const finalParams = { ...params, ...extraParams };
      const data = await tracksService.getTracks(finalParams);
      
      if (resetPage) {
        setTracks(data);
        setPage(1);
      } else {
        setTracks(prev => [...prev, ...data]);
        setPage(prev => prev + 1);
      }
      
      setHasMore(data.length === limit);
    } catch (error) {
      console.error("Search failed", error);
    } finally {
      setLoading(false);
    }
  }, [query, filters, limit, page, JSON.stringify(extraParams)]);

  // Debounce search (reset page)
  useEffect(() => {
    const t = setTimeout(() => search(true), 300);
    return () => clearTimeout(t);
  }, [query, filters, JSON.stringify(extraParams)]);

  const loadMore = () => {
    if (!loading && hasMore) {
      search(false);
    }
  };

  const applyFilters = (newFilters: FilterState, presetName: string = "custom") => {
    setFilters(newFilters);
    setCurrentPreset(presetName);
    setIsFilterOpen(false);
  };

  const clearAllFilters = () => {
    setQuery("");
    setFilters(INITIAL_FILTERS);
    setCurrentPreset("custom");
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

  return {
    query,
    setQuery,
    tracks,
    loading,
    filters,
    setFilters,
    currentPreset,
    isFilterOpen,
    setIsFilterOpen,
    applyFilters,
    clearAllFilters,
    search,
    loadMore,
    hasMore,
    activeFilterCount,
    setTracks,
  };
}
