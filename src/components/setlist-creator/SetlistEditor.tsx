import { useState } from "react";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Track } from "@/types";
import { GripVertical, X, Clock, Play } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { formatDuration } from "@/lib/utils";

interface SetlistEditorProps {
  tracks: Track[];
  onRemoveTrack: (index: number) => void;
  onReorder: (dragIndex: number, hoverIndex: number) => void;
  onDropTrack: (track: Track) => void;
  onTrackSelect: (track: Track) => void;
  selectedTrackId: number | null;
  onPlay: (track: Track) => void;
  currentTrackId?: number | null;
}

export function SetlistEditor({
  tracks,
  onRemoveTrack,
  onReorder,
  onDropTrack,
  onTrackSelect,
  selectedTrackId,
  onPlay,
  currentTrackId,
}: SetlistEditorProps) {
  const [draggedIndex, setDraggedIndex] = useState<number | null>(null);
  const [isDraggable, setIsDraggable] = useState(false);

  const handleDragStart = (e: React.DragEvent, index: number) => {
    if (!isDraggable) {
      e.preventDefault();
      return;
    }

    setDraggedIndex(index);
    e.dataTransfer.effectAllowed = "copyMove"; // Allow both move (reorder) and copy (to AutoTab)

    // Internal reorder identifier
    e.dataTransfer.setData("type", "INTERNAL_REORDER");
    e.dataTransfer.setData("index", index.toString());

    // ★ Add track data for external drops (e.g. into AutoTab Bridge)
    e.dataTransfer.setData("track", JSON.stringify(tracks[index]));
  };

  const handleDragOver = (e: React.DragEvent, index: number) => {
    e.preventDefault();
    e.dataTransfer.dropEffect = "move";
  };

  const handleDrop = (e: React.DragEvent, index: number) => {
    e.preventDefault();
    const type = e.dataTransfer.getData("type");

    if (type === "INTERNAL_REORDER" && draggedIndex !== null) {
      onReorder(draggedIndex, index);
    } else if (type === "NEW_TRACK") {
      try {
        const trackData = JSON.parse(e.dataTransfer.getData("track"));
        onDropTrack(trackData);
      } catch (err) {
        console.error("Failed to parse dropped track", err);
      }
    }
    setDraggedIndex(null);
    setIsDraggable(false);
  };

  const handleContainerDrop = (e: React.DragEvent) => {
    e.preventDefault();
    const type = e.dataTransfer.getData("type");
    if (type === "NEW_TRACK") {
      try {
        const trackData = JSON.parse(e.dataTransfer.getData("track"));
        onDropTrack(trackData);
      } catch (err) {
        console.error("Failed to parse dropped track", err);
      }
    }
  };

  const totalDuration = tracks.reduce((acc, t) => acc + (t.duration || 0), 0);

  return (
    <div
      className="flex-1 flex flex-col bg-muted/10"
      onDragOver={(e) => e.preventDefault()}
      onDrop={handleContainerDrop}
    >
      <div className="p-4 border-b bg-background flex justify-between items-center shadow-sm z-10">
        <h3 className="font-semibold">Current Setlist</h3>
        <div className="flex items-center gap-2 text-sm text-muted-foreground bg-muted px-2 py-1 rounded">
          <Clock className="h-4 w-4" />
          <span>Total: {formatDuration(totalDuration)}</span>
          <span>({tracks.length} tracks)</span>
        </div>
      </div>

      <ScrollArea className="flex-1 p-4">
        {tracks.length === 0 ? (
          <div className="h-full flex flex-col items-center justify-center text-muted-foreground border-2 border-dashed rounded-lg p-10">
            <p>Drag & Drop tracks here</p>
            <p className="text-xs mt-2">from the library on the right</p>
          </div>
        ) : (
          <div className="space-y-2 pb-20">
            {tracks.map((track, index) => {
              const isPlaying = currentTrackId === track.id;

              return (
                <div
                  key={`${track.id}-${index}`}
                  draggable={isDraggable}
                  onDragStart={(e) => handleDragStart(e, index)}
                  onDragOver={(e) => handleDragOver(e, index)}
                  onDrop={(e) => handleDrop(e, index)}
                  onClick={() => onTrackSelect(track)}
                  className={`group flex items-center gap-2 p-2 rounded-md border bg-card shadow-sm transition-all hover:shadow-md ${
                    selectedTrackId === track.id ? "ring-2 ring-primary" : ""
                  } ${isPlaying ? "bg-accent/30" : ""}`}
                >
                  <div
                    className="cursor-grab active:cursor-grabbing p-1 text-muted-foreground hover:text-foreground"
                    onMouseDown={() => setIsDraggable(true)}
                    onMouseUp={() => setIsDraggable(false)}
                    onMouseLeave={() => setIsDraggable(false)}
                  >
                    <GripVertical className="h-4 w-4" />
                  </div>

                  <Button
                    variant="ghost"
                    size="icon"
                    className="h-8 w-8 shrink-0 rounded-full"
                    onClick={(e) => {
                      e.stopPropagation();
                      onPlay(track);
                    }}
                  >
                    <Play
                      className={`h-4 w-4 ${
                        isPlaying ? "fill-green-500 text-green-500" : ""
                      }`}
                    />
                  </Button>

                  <div className="flex-1 min-w-0">
                    <div className="flex items-center justify-between">
                      <span className="font-medium truncate">
                        {track.title}
                      </span>
                      <span className="text-xs font-mono text-muted-foreground ml-2 shrink-0">
                        {formatDuration(track.duration)}
                      </span>
                    </div>
                    <div className="flex items-center gap-2 text-xs text-muted-foreground truncate">
                      <span className="truncate">{track.artist}</span>
                      {track.bpm > 0 && (
                        <Badge
                          variant="outline"
                          className="text-[10px] h-4 px-1 shrink-0"
                        >
                          {track.bpm.toFixed(0)}
                        </Badge>
                      )}
                      {track.key && (
                        <Badge
                          variant="outline"
                          className="text-[10px] h-4 px-1 shrink-0"
                        >
                          {track.key}
                        </Badge>
                      )}
                    </div>
                  </div>

                  <Button
                    variant="ghost"
                    size="icon"
                    className="h-6 w-6 opacity-0 group-hover:opacity-100 transition-opacity text-muted-foreground hover:text-destructive"
                    onClick={(e) => {
                      e.stopPropagation();
                      onRemoveTrack(index);
                    }}
                  >
                    <X className="h-4 w-4" />
                  </Button>
                </div>
              );
            })}
          </div>
        )}
      </ScrollArea>
    </div>
  );
}
