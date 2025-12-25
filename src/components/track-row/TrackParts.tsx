import { Track } from "@/types";
import { Button } from "@/components/ui/button";
import { Play, Pause, Mic } from "lucide-react";
import { cn } from "@/lib/utils";
import { usePlayerStore } from "@/stores/playerStore";

interface TrackPlayButtonProps {
  track: Track;
  disabled?: boolean;
  className?: string;
}

export function TrackPlayButton({
  track,
  disabled,
  className,
}: TrackPlayButtonProps) {
  const { currentTrack, isPlaying, play, pause } = usePlayerStore();
  const isCurrentTrack = currentTrack?.id === track.id;
  const isTrackPlaying = isCurrentTrack && isPlaying;

  const handlePlayClick = (e: React.MouseEvent) => {
    e.stopPropagation();
    if (isTrackPlaying) {
      pause();
    } else {
      play(track);
    }
  };

  return (
    <Button
      variant="ghost"
      size="icon"
      className={cn("h-8 w-8 hover:text-green-500 shrink-0", className)}
      onClick={handlePlayClick}
      disabled={disabled}
    >
      {isTrackPlaying ? (
        <Pause className="h-4 w-4 fill-green-500 text-green-500" />
      ) : (
        <Play className="h-4 w-4" />
      )}
    </Button>
  );
}

export function TrackTitle({ track, className }: { track: Track; className?: string }) {
  return (
    <div className={cn("flex flex-col min-w-0", className)}>
      <div className="flex items-center gap-1">
        {track.has_lyrics && (
          <Mic className="h-3 w-3 text-blue-500 shrink-0" aria-label="Has lyrics" />
        )}
        <span className="font-medium truncate text-sm" title={track.title}>
          {track.title}
        </span>
      </div>
      <span className="text-xs text-muted-foreground truncate" title={track.artist}>
        {track.artist}
      </span>
    </div>
  );
}

export function TrackMetaCell({ 
  value, 
  className,
  align = "left" 
}: { 
  value: string | number | undefined; 
  label?: string;
  className?: string;
  align?: "left" | "center" | "right";
}) {
  return (
    <div className={cn(
      "text-sm truncate", 
      align === "center" && "text-center",
      align === "right" && "text-right",
      className
    )} title={value?.toString()}>
      {value || "-"}
    </div>
  );
}

export function TrackAttributeCell({
  value,
  color = "bg-primary",
}: {
  value: number | undefined;
  color?: string;
}) {
  if (value === undefined || value === null)
    return <div className="text-center text-muted-foreground text-xs">-</div>;

  const percentage = Math.round(value * 100);

  return (
    <div className="flex items-center gap-2 w-full" title={`${percentage}%`}>
      <div className="flex-1 h-1.5 bg-muted/50 rounded-full overflow-hidden">
        <div
          className={cn("h-full rounded-full", color)}
          style={{ width: `${percentage}%` }}
        />
      </div>
      <span className="text-[10px] text-muted-foreground w-5 text-right tabular-nums">
        {percentage}
      </span>
    </div>
  );
}
