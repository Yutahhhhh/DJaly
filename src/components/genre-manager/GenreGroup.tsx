import React, { useState } from "react";
import { TrackSuggestion } from "@/services/genres";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { PlayButton } from "@/components/ui/PlayButton";
import {
  Loader2,
  ChevronRight,
  ChevronDown,
  ArrowRight,
} from "lucide-react";
import { Track } from "@/types";

export interface GenreGroupProps {
  id: string | number;
  title: string;
  subtitle?: string;
  badges?: React.ReactNode;
  count: number;

  // Data
  suggestions?: TrackSuggestion[];
  isLoadingSuggestions: boolean;

  // Selection State
  selectedIds: number[];
  onToggleSelection: (childId: number) => void;
  onToggleAll: (childIds: number[]) => void;

  // Actions
  onConfirm: () => void;
  onPlay: (track: Track | TrackSuggestion) => void;
  onExpand: () => void;

  // Customization
  confirmLabel?: string;
  showCurrentGenre?: boolean; // For cleanup view
}

export const GenreGroup: React.FC<GenreGroupProps> = ({
  title,
  subtitle,
  badges,
  count,
  suggestions,
  isLoadingSuggestions,
  selectedIds,
  onToggleSelection,
  onToggleAll,
  onConfirm,
  onExpand,
  confirmLabel = "Confirm",
  showCurrentGenre = false,
}) => {
  const [isExpanded, setIsExpanded] = useState(false);

  const handleExpandClick = () => {
    const nextState = !isExpanded;
    setIsExpanded(nextState);
    if (nextState && !suggestions) {
      onExpand();
    }
  };

  const hasSuggestions = suggestions && suggestions.length > 0;
  const hasSelection = selectedIds.length > 0;
  const allSelected =
    hasSuggestions && selectedIds.length === suggestions.length;

  return (
    <div className="border rounded-md bg-card">
      <div className="flex items-center justify-between p-3">
        <div className="flex items-center gap-3 overflow-hidden flex-1">
          <Button
            variant="ghost"
            size="icon"
            className="h-6 w-6 shrink-0"
            onClick={handleExpandClick}
          >
            {isExpanded ? (
              <ChevronDown className="h-4 w-4" />
            ) : (
              <ChevronRight className="h-4 w-4" />
            )}
          </Button>

          <Checkbox
            checked={allSelected}
            disabled={!isExpanded && !hasSuggestions} // Only enable if we know what we are selecting
            onCheckedChange={() => {
              if (!isExpanded && !suggestions) {
                // Auto expand on check if not loaded
                handleExpandClick();
              } else if (hasSuggestions) {
                onToggleAll(suggestions!.map((t) => t.id));
              }
            }}
          />

          {/* Header Info */}
          <div
            className="min-w-0 flex-1 cursor-pointer"
            onClick={handleExpandClick}
          >
            <div className="font-medium flex items-center gap-2 truncate">
              <span className="truncate text-base">{title}</span>
              {badges}
            </div>
            {subtitle && (
              <div className="text-sm text-muted-foreground truncate">
                {subtitle}
              </div>
            )}
          </div>
        </div>

        <div className="flex items-center gap-2 shrink-0 ml-2">
          <span className="text-xs text-muted-foreground hidden sm:inline-block">
            {count} tracks
          </span>
          <Button
            size="sm"
            onClick={(e) => {
              e.stopPropagation();
              onConfirm();
            }}
            disabled={!hasSelection}
          >
            {confirmLabel} ({selectedIds.length})
          </Button>
        </div>
      </div>

      {isExpanded && (
        <div className="border-t bg-muted/20 p-2 space-y-1">
          {isLoadingSuggestions ? (
            <div className="flex justify-center p-4">
              <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
            </div>
          ) : hasSuggestions ? (
            suggestions!.map((suggestion) => (
              <div
                key={suggestion.id}
                className="flex items-center gap-3 p-2 rounded-md hover:bg-muted/50 group/item"
              >
                <Checkbox
                  checked={selectedIds.includes(suggestion.id)}
                  onCheckedChange={() => onToggleSelection(suggestion.id)}
                />
                <PlayButton
                  track={suggestion}
                  variant="ghost"
                  size="icon"
                  className="h-6 w-6 opacity-0 group-hover/item:opacity-100 transition-opacity"
                  iconClassName="h-3 w-3"
                />
                <div className="flex-1 min-w-0 flex items-center gap-2">
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-sm font-medium">
                      {suggestion.title}
                    </div>
                    <div className="truncate text-xs text-muted-foreground">
                      {suggestion.artist}
                    </div>
                  </div>
                  {showCurrentGenre && suggestion.current_genre && (
                    <div className="flex items-center text-xs text-muted-foreground shrink-0 bg-background border px-1.5 py-0.5 rounded">
                      <span className="line-through opacity-70 mr-1">
                        {suggestion.current_genre}
                      </span>
                      <ArrowRight className="h-3 w-3 mx-1" />
                      <span className="font-medium text-primary">{title}</span>
                    </div>
                  )}
                </div>
                <div className="text-xs text-muted-foreground font-mono shrink-0">
                  {suggestion.bpm.toFixed(0)} BPM
                </div>
              </div>
            ))
          ) : (
            <div className="p-4 text-sm text-muted-foreground italic text-center">
              No tracks found.
            </div>
          )}
        </div>
      )}
    </div>
  );
};
