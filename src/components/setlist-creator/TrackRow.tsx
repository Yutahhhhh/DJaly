import { useState } from "react";
import { Button } from "@/components/ui/button";
import {
  Play,
  GripVertical,
  Plus,
} from "lucide-react";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { Track } from "@/types";
import { formatDuration } from "@/lib/utils";

interface TrackRowProps {
  track: Track;
  currentTrackId?: number | null;
  onPlay: (track: Track) => void;
  onAddTrack: (track: Track) => void;
}

export const TrackRow = ({ track, currentTrackId, onPlay, onAddTrack }: TrackRowProps) => {
  const isPlaying = currentTrackId === track.id;
  const [isDraggable, setIsDraggable] = useState(false);

  const handleDragStart = (e: React.DragEvent) => {
    if (!isDraggable) {
      e.preventDefault();
      return;
    }
    e.dataTransfer.setData("type", "NEW_TRACK");
    e.dataTransfer.setData("track", JSON.stringify(track));
    e.dataTransfer.effectAllowed = "copy";
  };

  return (
    <div
      draggable={isDraggable}
      onDragStart={handleDragStart}
      className={`group flex items-center gap-2 p-2 border-b last:border-0 hover:bg-muted/50 transition-colors bg-background ${
        isPlaying ? "bg-accent/30" : ""
      }`}
    >
      <div
        className="cursor-grab active:cursor-grabbing p-1 text-muted-foreground/50 hover:text-foreground"
        onMouseDown={() => setIsDraggable(true)}
        onMouseUp={() => setIsDraggable(false)}
        onMouseLeave={() => setIsDraggable(false)}
      >
        <GripVertical className="h-4 w-4 shrink-0" />
      </div>

      <Button
        variant="ghost"
        size="icon"
        className="h-8 w-8 shrink-0"
        onClick={() => onPlay(track)}
      >
        <Play
          className={`h-4 w-4 ${
            isPlaying
              ? "fill-green-500 text-green-500"
              : "text-muted-foreground"
          }`}
        />
      </Button>

      <div className="flex-1 min-w-0 grid grid-cols-[1fr_auto] gap-2 items-center">
        <div className="overflow-hidden">
          <div className="font-medium truncate text-sm" title={track.title}>
            {track.title}
          </div>
          <div
            className="text-xs text-muted-foreground truncate"
            title={track.artist}
          >
            {track.artist}
          </div>
          <div className="text-[10px] text-muted-foreground/70 truncate" title={track.genre}>
            {track.genre || "Unknown Genre"}
          </div>
        </div>

        <div className="flex items-center gap-2">
          <div className="flex flex-col items-end gap-0.5 min-w-[40px]">
            <span className="text-xs font-mono font-medium">
              {track.bpm ? track.bpm.toFixed(0) : "-"}
            </span>
            <span className="text-[10px] text-muted-foreground font-mono">
              {track.key || "-"}
            </span>
            <span className="text-[10px] text-muted-foreground font-mono">
              {formatDuration(track.duration)}
            </span>
          </div>

          <div className="flex gap-1">
            {track.energy > 0 && (
              <TooltipProvider>
                <Tooltip>
                  <TooltipTrigger asChild>
                    <div className="w-1.5 h-6 bg-secondary rounded-full overflow-hidden cursor-help relative">
                      <div
                        className="w-full bg-orange-500 absolute bottom-0 left-0 transition-all duration-300"
                        style={{ height: `${track.energy * 100}%` }}
                      />
                    </div>
                  </TooltipTrigger>
                  <TooltipContent side="left">
                    Energy: {track.energy}
                  </TooltipContent>
                </Tooltip>
              </TooltipProvider>
            )}
          </div>

          <Button
            size="sm"
            variant="secondary"
            className="h-7 px-2 ml-1"
            onClick={() => onAddTrack(track)}
          >
            <Plus className="h-4 w-4" />
          </Button>
        </div>
      </div>
    </div>
  );
};
