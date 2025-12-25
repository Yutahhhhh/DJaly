import React, { useEffect, useState, useRef, useCallback } from "react";
import {
  genreService,
  GroupedSuggestionSummary,
  TrackSuggestion,
} from "@/services/genres";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Loader2 } from "lucide-react";
import { Track } from "@/types";
import { GenreGroup } from "./GenreGroup";

import { AnalysisMode } from "@/services/genres";

interface AnalyzeMissingTabProps {
  onPlay: (track: Track) => void;
  mode?: AnalysisMode;
}

export const AnalyzeMissingTab: React.FC<AnalyzeMissingTabProps> = ({
  onPlay,
  mode = "both"
}) => {
  const [groups, setGroups] = useState<GroupedSuggestionSummary[]>([]);
  const [loadedSuggestions, setLoadedSuggestions] = useState<
    Record<number, TrackSuggestion[]>
  >({});
  const [loadingSuggestions, setLoadingSuggestions] = useState<
    Record<number, boolean>
  >({});
  const [loading, setLoading] = useState(false);
  const [selectedTracks, setSelectedTracks] = useState<
    Record<number, number[]>
  >({}); // parentId -> selected childIds

  // Pagination
  const [offset, setOffset] = useState(0);
  const [hasMore, setHasMore] = useState(true);
  const LIMIT = 20;

  const observer = useRef<IntersectionObserver | null>(null);
  const lastElementRef = useCallback(
    (node: HTMLDivElement | null) => {
      if (loading) return;
      if (observer.current) observer.current.disconnect();
      observer.current = new IntersectionObserver((entries) => {
        if (entries[0].isIntersecting && hasMore) {
          setOffset((prev) => prev + LIMIT);
        }
      });
      if (node) observer.current.observe(node);
    },
    [loading, hasMore]
  );

  const fetchGroups = async (reset = false) => {
    setLoading(true);
    try {
      const currentOffset = reset ? 0 : offset;
      const data = await genreService.getGroupedSuggestions(
        currentOffset,
        LIMIT,
        0.85,
        mode
      );

      if (data.length < LIMIT) {
        setHasMore(false);
      }

      setGroups((prev) => (reset ? data : [...prev, ...data]));
    } catch (error) {
      console.error("Failed to fetch groups", error);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    // Reset when mode changes
    setOffset(0);
    setHasMore(true);
    setGroups([]);
    fetchGroups(true);
  }, [mode]);

  useEffect(() => {
    if (offset > 0) {
      fetchGroups(false);
    }
  }, [offset]);

  const handleExpandGroup = async (parentId: number) => {
    if (loadedSuggestions[parentId] || loadingSuggestions[parentId]) return;

    setLoadingSuggestions((prev) => ({ ...prev, [parentId]: true }));
    try {
      const suggestions = await genreService.getSuggestionsForTrack(parentId);
      setLoadedSuggestions((prev) => ({ ...prev, [parentId]: suggestions }));
    } catch (error) {
      console.error(
        `Failed to fetch suggestions for parent ${parentId}`,
        error
      );
    } finally {
      setLoadingSuggestions((prev) => ({ ...prev, [parentId]: false }));
    }
  };

  const toggleSelection = (parentId: number, childId: number) => {
    setSelectedTracks((prev) => {
      const current = prev[parentId] || [];
      if (current.includes(childId)) {
        return { ...prev, [parentId]: current.filter((id) => id !== childId) };
      } else {
        return { ...prev, [parentId]: [...current, childId] };
      }
    });
  };

  const toggleAllInGroup = (parentId: number, childIds: number[]) => {
    setSelectedTracks((prev) => {
      const current = prev[parentId] || [];
      if (current.length === childIds.length) {
        // Deselect all
        const { [parentId]: _, ...rest } = prev;
        return rest;
      } else {
        // Select all
        return { ...prev, [parentId]: childIds };
      }
    });
  };

  const handleConfirm = async (parentId: number) => {
    const targetIds = selectedTracks[parentId];
    if (!targetIds || targetIds.length === 0) return;

    try {
      await genreService.batchUpdateGenres(parentId, targetIds);

      // Remove the processed group from the list locally to avoid refetching immediately
      setGroups((prev) => prev.filter((g) => g.parent_track.id !== parentId));

      setSelectedTracks((prev) => {
        const { [parentId]: _, ...rest } = prev;
        return rest;
      });
    } catch (error) {
      console.error("Failed to update genres", error);
    }
  };

  const handlePlay = (track: any) => {
    onPlay(track as Track);
  };

  const handleRefresh = () => {
    setOffset(0);
    setHasMore(true);
    setGroups([]);
    setLoadedSuggestions({});
    if (offset === 0) fetchGroups(true);
  };

  return (
    <div className="h-full flex flex-col">
      <div className="p-4 border-b flex justify-between items-center shrink-0">
        <div>
          <h3 className="font-medium">Group by Similarity ({mode})</h3>
          <p className="text-sm text-muted-foreground">
            Verified tracks are used as reference to find similar unverified
            tracks.
          </p>
        </div>
        <Button
          variant="outline"
          size="sm"
          onClick={handleRefresh}
          disabled={loading}
        >
          {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : "Refresh"}
        </Button>
      </div>

      <div className="flex-1 min-h-0">
        <ScrollArea className="h-full">
          <div className="p-4 space-y-4">
            {groups.map((group, index) => (
              <div
                key={group.parent_track.id}
                ref={index === groups.length - 1 ? lastElementRef : null}
              >
                <GenreGroup
                  id={group.parent_track.id}
                  title={group.parent_track.title}
                  subtitle={group.parent_track.artist}
                  badges={
                    <span className="text-xs bg-primary/10 text-primary px-2 py-0.5 rounded-full shrink-0">
                      {mode === "subgenre" ? (group.parent_track.subgenre || "No Subgenre") : group.parent_track.genre}
                    </span>
                  }
                  count={group.suggestion_count}
                  suggestions={loadedSuggestions[group.parent_track.id]}
                  isLoadingSuggestions={
                    !!loadingSuggestions[group.parent_track.id]
                  }
                  selectedIds={selectedTracks[group.parent_track.id] || []}
                  onToggleSelection={(childId) =>
                    toggleSelection(group.parent_track.id, childId)
                  }
                  onToggleAll={(childIds) =>
                    toggleAllInGroup(group.parent_track.id, childIds)
                  }
                  onConfirm={() => handleConfirm(group.parent_track.id)}
                  onPlay={(t) =>
                    handlePlay(
                      t.id === group.parent_track.id ? group.parent_track : t
                    )
                  }
                  onExpand={() => handleExpandGroup(group.parent_track.id)}
                />
              </div>
            ))}

            {loading && (
              <div className="flex justify-center p-4">
                <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
              </div>
            )}

            {!loading && groups.length === 0 && (
              <div className="text-center p-8 text-muted-foreground">
                No suggestions found. Try analyzing more tracks first.
              </div>
            )}
          </div>
        </ScrollArea>
      </div>
    </div>
  );
};
