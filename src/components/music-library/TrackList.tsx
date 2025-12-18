import { ScrollArea } from "@/components/ui/scroll-area";
import { Button } from "@/components/ui/button";
import { RefreshCw, Loader2, Play } from "lucide-react";
import { Track } from "@/types";
import { GenreCell } from "./GenreCell";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";

interface TrackListProps {
  tracks: Track[];
  isLoading?: boolean;
  onPlay: (track: Track) => void;
  currentTrackId?: number | null;
  lastTrackElementRef: (node: HTMLTableRowElement | null) => void;
  analyzingId: number | null;
  onAnalyze: (track: Track) => void;
  disabled?: boolean;
  onTrackUpdate?: (trackId: number, updates: Partial<Track>) => void;
}

export function TrackList({
  tracks,
  isLoading = false,
  onPlay,
  currentTrackId,
  lastTrackElementRef,
  analyzingId,
  onAnalyze,
  disabled = false,
  onTrackUpdate,
}: TrackListProps) {
  return (
    <div className="flex-1 border rounded-md overflow-hidden bg-card relative">
      {isLoading && (
        <div className="absolute inset-0 bg-background/50 backdrop-blur-sm z-50 flex items-center justify-center">
          <div className="flex flex-col items-center gap-2">
            <Loader2 className="h-8 w-8 animate-spin text-primary" />
            <p className="text-sm text-muted-foreground">Loading tracks...</p>
          </div>
        </div>
      )}
      <ScrollArea className="h-full">
        <div className="p-0">
          <table className="w-full text-sm text-left">
            <thead className="text-muted-foreground border-b sticky top-0 bg-background z-10">
              <tr>
                <th className="p-3 font-medium w-10"></th>
                <th className="p-3 font-medium min-w-[200px]">
                  Title / Artist
                </th>
                <th className="p-3 font-medium w-[120px]">Genre</th>
                <th className="p-3 font-medium text-right w-[80px]">BPM</th>
                <th className="p-3 font-medium text-center w-[80px]">Key</th>
                <th className="p-3 font-medium text-center w-[80px]">Energy</th>
                <th className="p-3 font-medium text-center w-[80px]">Dance</th>
                <th className="p-3 font-medium">Tags</th>
                <th className="p-3 font-medium w-[100px]">Action</th>
              </tr>
            </thead>
            <tbody>
              <TooltipProvider>
                {tracks.map((track, index) => {
                  const isUnanalyzed = !track.bpm || track.bpm === 0;
                  const isPlaying = currentTrackId === track.id;

                  // Parse Genre (Metadata) vs Tags (LLM)
                  // Backend stores: "Genre | Tag1, Tag2"
                  const genreParts = track.genre ? track.genre.split("|") : [];
                  const displayTags =
                    genreParts.length > 1 ? genreParts[1].trim() : "";

                  return (
                    <tr
                      ref={
                        tracks.length === index + 1 ? lastTrackElementRef : null
                      }
                      key={track.id}
                      className={`border-b transition-colors ${
                        isPlaying ? "bg-accent/50" : ""
                      } ${
                        isUnanalyzed ? "bg-yellow-50/5" : "hover:bg-muted/50"
                      } ${disabled ? "opacity-50 cursor-not-allowed" : ""}`}
                      onDoubleClick={() => !disabled && onPlay(track)}
                    >
                      <td className="p-2 text-center">
                        <Button
                          variant="ghost"
                          size="icon"
                          className="h-8 w-8 hover:text-green-500"
                          onClick={() => !disabled && onPlay(track)}
                          disabled={disabled}
                        >
                          <Play
                            className={`h-4 w-4 ${
                              isPlaying ? "fill-green-500 text-green-500" : ""
                            }`}
                          />
                        </Button>
                      </td>
                      <td className="p-3 max-w-[200px]">
                        <div
                          className="font-medium truncate"
                          title={track.title}
                        >
                          {track.title}
                        </div>
                        <div
                          className="text-xs text-muted-foreground truncate"
                          title={track.artist}
                        >
                          {track.artist}
                        </div>
                      </td>

                      {/* Genre Column (Metadata) */}
                      <td className="p-3 max-w-[120px]">
                        <GenreCell 
                          track={track} 
                          onUpdate={(id, genre) => onTrackUpdate?.(id, { genre, is_genre_verified: true })} 
                        />
                      </td>

                      <td className="p-3 text-right font-mono">
                        {track.bpm ? track.bpm.toFixed(1) : "-"}
                      </td>

                      {/* Key Column (Key includes Scale info e.g., "C Major") */}
                      <td className="p-3 text-center font-mono text-xs">
                        {track.key || "-"}
                      </td>

                      {/* Visual Indicators for Features */}
                      <td className="p-3 text-center">
                        {track.energy > 0 && (
                          <Tooltip>
                            <TooltipTrigger>
                              <div className="w-12 h-1.5 bg-secondary rounded-full overflow-hidden mx-auto cursor-help">
                                <div
                                  className="h-full bg-orange-500"
                                  style={{ width: `${track.energy * 100}%` }}
                                />
                              </div>
                            </TooltipTrigger>
                            <TooltipContent>
                              Energy: {track.energy}
                            </TooltipContent>
                          </Tooltip>
                        )}
                      </td>
                      <td className="p-3 text-center">
                        {track.danceability > 0 && (
                          <Tooltip>
                            <TooltipTrigger>
                              <div className="w-12 h-1.5 bg-secondary rounded-full overflow-hidden mx-auto cursor-help">
                                <div
                                  className="h-full bg-blue-500"
                                  style={{
                                    width: `${track.danceability * 100}%`,
                                  }}
                                />
                              </div>
                            </TooltipTrigger>
                            <TooltipContent>
                              Danceability: {track.danceability}
                            </TooltipContent>
                          </Tooltip>
                        )}
                      </td>

                      {/* Tags Column (LLM) */}
                      <td className="p-3 max-w-[150px]">
                        <div
                          className="truncate text-xs text-muted-foreground"
                          title={displayTags}
                        >
                          {displayTags ? displayTags.replace(/,/g, " •") : "-"}
                        </div>
                      </td>

                      <td className="p-2 text-center flex gap-1 justify-center">
                        <Button
                          variant="ghost"
                          size="icon"
                          title="Re-analyze"
                          onClick={(e) => {
                            e.stopPropagation();
                            onAnalyze(track);
                          }}
                          disabled={analyzingId === track.id}
                        >
                          {analyzingId === track.id ? (
                            <Loader2 className="h-4 w-4 animate-spin" />
                          ) : (
                            <RefreshCw className="h-4 w-4 text-muted-foreground" />
                          )}
                        </Button>
                      </td>
                    </tr>
                  );
                })}
              </TooltipProvider>
            </tbody>
          </table>
        </div>
      </ScrollArea>
    </div>
  );
}
