import { ScrollArea } from "@/components/ui/scroll-area";
import { Loader2, RefreshCw } from "lucide-react";
import { Track } from "@/types";
import { TrackRow } from "@/components/track-row";
import { Button } from "@/components/ui/button";
import {
  TooltipProvider,
} from "@/components/ui/tooltip";

interface TrackListProps {
  tracks: Track[];
  isLoading?: boolean;
  lastTrackElementRef: (node: HTMLTableRowElement | null) => void;
  analyzingId: number | null;
  onAnalyze: (track: Track) => void;
  disabled?: boolean;
  onTrackUpdate?: (trackId: number, updates: Partial<Track>) => void;
}

export function TrackList({
  tracks,
  isLoading = false,
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
                <th className="p-3 font-medium w-20">Year</th>
                <th className="p-3 font-medium w-[120px]">Genre</th>
                <th className="p-3 font-medium text-right w-20">BPM</th>
                <th className="p-3 font-medium text-center w-20">Key</th>
                <th className="p-3 font-medium text-center w-20">Energy</th>
                <th className="p-3 font-medium text-center w-20">Dance</th>
                <th className="p-3 font-medium w-[120px]">Subgenre</th>
                <th className="p-3 font-medium w-[100px]">Action</th>
              </tr>
            </thead>
            <tbody>
              <TooltipProvider>
                {tracks.map((track, index) => {
                  const isUnanalyzed = !track.bpm || track.bpm === 0;

                  return (
                    <TrackRow
                      key={track.id}
                      track={track}
                      viewType="table"
                      isUnanalyzed={isUnanalyzed}
                      disabled={disabled}
                      onTrackUpdate={onTrackUpdate}
                      innerRef={tracks.length === index + 1 ? lastTrackElementRef : null}
                      suffix={
                        <div className="flex justify-center">
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
                        </div>
                      }
                    />
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
