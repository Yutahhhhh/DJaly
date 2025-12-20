import React from "react";
import { Button } from "@/components/ui/button";
import { Play, GripVertical, X, Plus } from "lucide-react";
import { Track } from "@/types";
import { formatDuration } from "@/lib/utils";
import { useSortable } from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { cn } from "@/lib/utils";

interface TrackRowProps {
  id: string;
  track: Track;
  type: "SETLIST_ITEM" | "LIBRARY_ITEM" | "RECOMMEND_ITEM";
  isPlaying?: boolean;
  isSelected?: boolean;
  onPlay: () => void;
  onSelect?: () => void;
  onRemove?: () => void;
  onAdd?: () => void;
}

export const TrackRow = React.memo(
  ({
    id,
    track,
    type,
    isPlaying,
    isSelected,
    onPlay,
    onSelect,
    onRemove,
    onAdd,
  }: TrackRowProps) => {
    const {
      attributes,
      listeners,
      setNodeRef,
      transform,
      transition,
      isDragging,
    } = useSortable({
      id: id,
      data: { type, track },
    });

    const style = {
      // translate3dではなくTranslate(2D)を使用してWebKitの描画を高速化
      transform: CSS.Translate.toString(transform),
      // ドラッグ中のラグを解消するために transition: none を徹底
      transition: isDragging ? "none" : transition,
      zIndex: isDragging ? 100 : undefined,
    };

    return (
      <div
        ref={setNodeRef}
        style={style}
        className={cn(
          "group flex items-center gap-2 p-2 rounded-md border bg-card transition-colors cursor-default select-none w-full overflow-hidden",
          // ドラッグされている「元」のアイテムだけを薄くする（Overlayは除外）
          isDragging &&
            id !== "overlay" &&
            "opacity-20 border-primary bg-primary/5",
          isSelected && "ring-2 ring-primary z-10",
          isPlaying && "bg-accent/50 border-primary/30"
        )}
        onClick={onSelect}
      >
        <div
          {...attributes}
          {...listeners}
          className="cursor-grab active:cursor-grabbing p-1 text-muted-foreground/50 hover:text-foreground shrink-0 z-20"
        >
          <GripVertical className="h-4 w-4" />
        </div>

        <Button
          variant="ghost"
          size="icon"
          className="h-8 w-8 shrink-0 rounded-full z-20"
          onClick={(e) => {
            e.stopPropagation();
            onPlay();
          }}
        >
          <Play
            className={cn(
              "h-4 w-4",
              isPlaying && "fill-green-500 text-green-500"
            )}
          />
        </Button>

        {/* レイアウト溢れ防止の核心: flex-1 min-w-0 */}
        <div className="flex-1 min-w-0 flex flex-col gap-0.5">
          <div className="flex items-center justify-between gap-2 w-full overflow-hidden">
            <span
              className="font-medium truncate text-sm flex-1"
              title={track.title}
            >
              {track.title}
            </span>
            <span className="text-[10px] font-mono text-muted-foreground shrink-0 tabular-nums">
              {formatDuration(track.duration)}
            </span>
          </div>
          <div className="text-[11px] text-muted-foreground truncate w-full">
            {track.artist} {track.bpm > 0 && `• ${track.bpm.toFixed(0)} BPM`}{" "}
            {track.key && `• ${track.key}`}
          </div>
        </div>

        <div className="flex gap-1 shrink-0 z-20 ml-1">
          {onAdd && (
            <Button
              variant="ghost"
              size="icon"
              className="h-7 w-7 opacity-0 group-hover:opacity-100 text-primary"
              onClick={(e) => {
                e.stopPropagation();
                onAdd();
              }}
            >
              <Plus className="h-4 w-4" />
            </Button>
          )}
          {onRemove && (
            <Button
              variant="ghost"
              size="icon"
              className="h-7 w-7 opacity-0 group-hover:opacity-100 text-muted-foreground hover:text-destructive"
              onClick={(e) => {
                e.stopPropagation();
                onRemove();
              }}
            >
              <X className="h-4 w-4" />
            </Button>
          )}
        </div>
      </div>
    );
  }
);

TrackRow.displayName = "TrackRow";
