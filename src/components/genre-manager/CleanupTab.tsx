import React, { useEffect, useState } from "react";
import {
  genreService,
  GenreCleanupGroup,
} from "@/services/genres";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Loader2, Wand2 } from "lucide-react";
import { Track } from "@/types";
import { GenreGroup } from "./GenreGroup";

import { AnalysisMode } from "@/services/genres";

interface CleanupTabProps {
  onPlay: (track: Track) => void;
  mode?: AnalysisMode;
}

export const CleanupTab: React.FC<CleanupTabProps> = ({ onPlay, mode = "both" }) => {
  const [groups, setGroups] = useState<GenreCleanupGroup[]>([]);
  const [loading, setLoading] = useState(false);
  const [selectedTracks, setSelectedTracks] = useState<
    Record<string, number[]>
  >({}); // primaryGenre -> selected childIds

  const fetchGroups = async () => {
    setLoading(true);
    try {
      const data = await genreService.getCleanupSuggestions(mode);
      setGroups(data);
    } catch (error) {
      console.error("Failed to fetch cleanup groups", error);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchGroups();
  }, [mode]);

  const toggleSelection = (primaryGenre: string, childId: number) => {
    setSelectedTracks((prev) => {
      const current = prev[primaryGenre] || [];
      if (current.includes(childId)) {
        return {
          ...prev,
          [primaryGenre]: current.filter((id) => id !== childId),
        };
      } else {
        return { ...prev, [primaryGenre]: [...current, childId] };
      }
    });
  };

  const toggleAllInGroup = (primaryGenre: string, childIds: number[]) => {
    setSelectedTracks((prev) => {
      const current = prev[primaryGenre] || [];
      if (current.length === childIds.length) {
        // Deselect all
        const { [primaryGenre]: _, ...rest } = prev;
        return rest;
      } else {
        // Select all
        return { ...prev, [primaryGenre]: childIds };
      }
    });
  };

  const handleConfirm = async (primaryGenre: string) => {
    const targetIds = selectedTracks[primaryGenre];
    if (!targetIds || targetIds.length === 0) return;

    try {
      await genreService.executeCleanup(primaryGenre, targetIds, mode);

      // Remove processed items locally or reduce counts
      // For simplicity, just refetch or filter out fully processed groups
      setGroups((prev) => {
        const newGroups = prev
          .map((g) => {
            if (g.primary_genre === primaryGenre) {
              // Remove updated tracks from suggestions
              const remaining = g.suggestions.filter(
                (s) => !targetIds.includes(s.id)
              );
              return {
                ...g,
                suggestions: remaining,
                track_count: remaining.length,
              };
            }
            return g;
          })
          .filter((g) => g.suggestions.length > 0);
        return newGroups;
      });

      setSelectedTracks((prev) => {
        const { [primaryGenre]: _, ...rest } = prev;
        return rest;
      });
    } catch (error) {
      console.error("Failed to cleanup genres", error);
    }
  };

  const handlePlay = (track: any) => {
    onPlay(track as Track);
  };

  const title = mode === "subgenre" ? "Subgenre Cleanup" : "Genre Cleanup";
  const description = mode === "subgenre" 
    ? 'Detect and unify inconsistent subgenre names.'
    : 'Detect and unify inconsistent genre names (e.g. "Hip-Hop" → "Hip Hop").';

  return (
    <div className="h-full flex flex-col">
      <div className="p-4 border-b flex justify-between items-center shrink-0">
        <div>
          <h3 className="font-medium flex items-center gap-2">
            <Wand2 className="h-4 w-4 text-purple-500" />
            {title}
          </h3>
          <p className="text-sm text-muted-foreground">
            {description}
          </p>
        </div>
        <Button
          variant="outline"
          size="sm"
          onClick={fetchGroups}
          disabled={loading}
        >
          {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : "Refresh"}
        </Button>
      </div>

      <div className="flex-1 min-h-0">
        <ScrollArea className="h-full">
          <div className="p-4 space-y-4">
            {groups.map((group) => (
              <div key={group.primary_genre}>
                <GenreGroup
                  id={group.primary_genre}
                  title={group.primary_genre}
                  subtitle={`${
                    group.variant_genres.length
                  } variations found: ${group.variant_genres.join(", ")}`}
                  badges={
                    <span className="text-xs bg-purple-100 text-purple-700 px-2 py-0.5 rounded-full shrink-0">
                      Suggested
                    </span>
                  }
                  count={group.track_count}
                  suggestions={group.suggestions}
                  isLoadingSuggestions={false} // Already loaded in bulk
                  selectedIds={selectedTracks[group.primary_genre] || []}
                  onToggleSelection={(childId) =>
                    toggleSelection(group.primary_genre, childId)
                  }
                  onToggleAll={(childIds) =>
                    toggleAllInGroup(group.primary_genre, childIds)
                  }
                  onConfirm={() => handleConfirm(group.primary_genre)}
                  onPlay={handlePlay}
                  onExpand={() => {}} // No async load needed
                  confirmLabel="Unify"
                  showCurrentGenre={true}
                />
              </div>
            ))}

            {loading && (
              <div className="flex justify-center p-4">
                <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
              </div>
            )}

            {!loading && groups.length === 0 && (
              <div className="flex flex-col items-center justify-center p-8 text-muted-foreground h-40">
                <div className="bg-green-50 text-green-600 p-3 rounded-full mb-3">
                  <Wand2 className="h-6 w-6" />
                </div>
                <p>No {mode} inconsistencies found!</p>
                <p className="text-xs">Your library metadata looks clean.</p>
              </div>
            )}
          </div>
        </ScrollArea>
      </div>
    </div>
  );
};
