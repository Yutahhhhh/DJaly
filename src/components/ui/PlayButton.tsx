import { Play, Pause } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Track } from "@/types";
import { usePlayerStore } from "@/stores/playerStore";
import { cn } from "@/lib/utils";

// Track互換の最小限のインターフェース
interface MinimalTrack {
  id: number;
  title: string;
  artist: string;
  filepath: string;
}

interface PlayButtonProps {
  track: Track | MinimalTrack;
  timestamp?: number | null;
  variant?: "default" | "ghost" | "outline" | "secondary";
  size?: "default" | "sm" | "lg" | "icon";
  className?: string;
  iconClassName?: string;
  showPauseWhenPlaying?: boolean;
  disabled?: boolean;
  children?: React.ReactNode;
}

export function PlayButton({
  track,
  timestamp,
  variant = "ghost",
  size = "icon",
  className,
  iconClassName,
  showPauseWhenPlaying = false,
  disabled = false,
  children,
}: PlayButtonProps) {
  const { currentTrack, isPlaying, play, playAt, pause } = usePlayerStore();

  const isCurrentTrack = currentTrack?.id === track.id;
  const isCurrentlyPlaying = isCurrentTrack && isPlaying;

  const handleClick = () => {
    if (isCurrentlyPlaying && showPauseWhenPlaying) {
      pause();
    } else if (timestamp !== undefined && timestamp !== null) {
      playAt(track as Track, timestamp);
    } else {
      play(track as Track);
    }
  };

  const iconClasses = cn(
    "h-4 w-4",
    isCurrentlyPlaying && "fill-current",
    iconClassName
  );

  return (
    <Button
      variant={variant}
      size={size}
      className={cn(
        "transition-all",
        isCurrentlyPlaying && "text-green-500",
        className
      )}
      onClick={handleClick}
      disabled={disabled}
    >
      {isCurrentlyPlaying && showPauseWhenPlaying ? (
        <Pause className={iconClasses} />
      ) : (
        <Play className={iconClasses} />
      )}
      {children}
    </Button>
  );
}
