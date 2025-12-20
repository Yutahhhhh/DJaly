import { ScrollArea } from "@/components/ui/scroll-area";
import { Track } from "@/types";
import { Clock } from "lucide-react";
import { formatDuration } from "@/lib/utils";
import {
  SortableContext,
  verticalListSortingStrategy,
} from "@dnd-kit/sortable";
import { TrackRow } from "./TrackRow";
import { useDroppable } from "@dnd-kit/core";

export interface SetlistEditorProps {
  tracks: Track[];
  onRemoveTrack: (index: number) => void;
  onTrackSelect: (track: Track) => void;
  selectedTrackId: number | null;
  onPlay: (track: Track) => void;
  currentTrackId?: number | null;
}

export function SetlistEditor({
  tracks,
  onRemoveTrack,
  onTrackSelect,
  selectedTrackId,
  onPlay,
  currentTrackId,
}: SetlistEditorProps) {
  const { setNodeRef } = useDroppable({ id: "setlist-editor-droppable" });
  const totalDuration = tracks.reduce(
    (acc: number, t: Track) => acc + (t.duration || 0),
    0
  );

  return (
    <div
      ref={setNodeRef}
      className="flex-1 flex flex-col bg-muted/10 border-r min-w-0"
    >
      <div className="p-4 border-b bg-background flex justify-between items-center shadow-sm z-10">
        <h3 className="font-semibold">Current Setlist</h3>
        <div className="flex items-center gap-2 text-sm text-muted-foreground bg-muted px-2 py-1 rounded">
          <Clock className="h-4 w-4" />
          <span>{formatDuration(totalDuration)}</span>
          <span className="opacity-30">|</span>
          <span>{tracks.length} tracks</span>
        </div>
      </div>

      <ScrollArea className="flex-1">
        <div className="p-4 space-y-2 pb-20">
          {tracks.length === 0 ? (
            <div className="h-64 flex flex-col items-center justify-center text-muted-foreground border-2 border-dashed rounded-lg">
              <p className="text-sm">Drag tracks here from the library</p>
            </div>
          ) : (
            <SortableContext
              items={tracks.map((t: Track) => `setlist-${t.id}`)}
              strategy={verticalListSortingStrategy}
            >
              {tracks.map((track: Track, index: number) => (
                <TrackRow
                  key={`setlist-${track.id}`}
                  id={`setlist-${track.id}`}
                  track={track}
                  type="SETLIST_ITEM"
                  isPlaying={currentTrackId === track.id}
                  isSelected={selectedTrackId === track.id}
                  onPlay={() => onPlay(track)}
                  onSelect={() => onTrackSelect(track)}
                  onRemove={() => onRemoveTrack(index)}
                />
              ))}
            </SortableContext>
          )}
        </div>
      </ScrollArea>
    </div>
  );
}
