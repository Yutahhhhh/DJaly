import React from "react";
import { Button } from "@/components/ui/button";
import { GripVertical, X, Plus, MessageSquareQuote } from "lucide-react";
import { Track } from "@/types";
import { useSortable } from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { TrackRow as BaseTrackRow } from "@/components/track-row";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";

interface TrackRowProps {
  id: string;
  track: Track;
  type: "SETLIST_ITEM" | "LIBRARY_ITEM" | "RECOMMEND_ITEM";
  isSelected?: boolean;
  disableDnD?: boolean;
  onSelect?: () => void;
  onRemove?: () => void;
  onAdd?: () => void;
  innerRef?: React.Ref<HTMLDivElement>;
}

const TrackRowContent = ({
  track,
  isSelected,
  onSelect,
  onRemove,
  onAdd,
  dragHandleProps,
  style,
  innerRef,
  isDragging,
}: Omit<TrackRowProps, "id" | "type" | "disableDnD"> & {
  dragHandleProps?: any;
  style?: React.CSSProperties;
  innerRef?: (node: HTMLElement | null) => void;
  isDragging?: boolean;
}) => {
  const wordplayData = React.useMemo(() => {
    if ('wordplay_json' in track && (track as any).wordplay_json) {
      try {
        return JSON.parse((track as any).wordplay_json);
      } catch (e) {
        return null;
      }
    }
    return null;
  }, [track]);

  return (
    <div className="relative group/row">
      {wordplayData && (
        <div className="absolute -top-3 left-12 z-30">
          <Popover>
            <PopoverTrigger asChild>
              <div 
                className="cursor-pointer bg-background border rounded-full p-1 shadow-sm hover:bg-accent hover:text-accent-foreground transition-colors" 
                onClick={(e) => e.stopPropagation()}
              >
                <MessageSquareQuote className="h-3 w-3 text-primary" />
              </div>
            </PopoverTrigger>
            <PopoverContent className="w-80 p-3" side="right" align="start">
              <div className="font-medium mb-2 flex items-center gap-2 text-sm">
                <MessageSquareQuote className="h-4 w-4 text-primary" /> 
                Wordplay Connection
              </div>
              <div className="space-y-2 text-sm">
                <div className="bg-muted/50 p-2 rounded border border-border/50">
                  <div className="text-xs text-muted-foreground mb-1">Source Phrase</div>
                  <div className="italic">"{wordplayData.source_phrase}"</div>
                </div>
                <div className="flex justify-center text-muted-foreground text-xs">
                  ↓ via <span className="font-bold mx-1 text-primary">{wordplayData.keyword}</span>
                </div>
                <div className="bg-primary/5 p-2 rounded border border-primary/20">
                  <div className="text-xs text-muted-foreground mb-1">Target Phrase</div>
                  <div className="italic">"{wordplayData.target_phrase}"</div>
                </div>
              </div>
            </PopoverContent>
          </Popover>
        </div>
      )}
      <BaseTrackRow
        track={track}
        viewType="list"
        isSelected={isSelected}
        onClick={onSelect}
        innerRef={innerRef}
        style={style}
        className={isDragging ? "opacity-20 border-primary bg-primary/5" : ""}
        showMeta={true} // Use standard meta rendering
      prefix={
        dragHandleProps ? (
          <div
            {...dragHandleProps}
            className="cursor-grab active:cursor-grabbing p-1 text-muted-foreground/50 hover:text-foreground shrink-0 z-20"
          >
            <GripVertical className="h-4 w-4" />
          </div>
        ) : (
          <div className="w-2" />
        )
      }
      suffix={
        <div className="flex gap-1 shrink-0 z-20 ml-1">
          {/* Duration is now handled by BaseTrackRow */}
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
      }
    />
    </div>
  );
};

const SortableTrackRow = (props: TrackRowProps) => {
  const {
    attributes,
    listeners,
    setNodeRef,
    transform,
    transition,
    isDragging,
  } = useSortable({
    id: props.id,
    data: { type: props.type, track: props.track },
  });

  const style = {
    transform: CSS.Translate.toString(transform),
    transition: isDragging ? "none" : transition,
    zIndex: isDragging ? 100 : undefined,
  };

  return (
    <TrackRowContent
      {...props}
      innerRef={setNodeRef}
      style={style}
      dragHandleProps={{ ...attributes, ...listeners }}
      isDragging={isDragging && props.id !== "overlay"}
    />
  );
};

export const TrackRow = React.memo((props: TrackRowProps) => {
  if (props.disableDnD) {
    return <TrackRowContent {...props} innerRef={props.innerRef as any} />;
  }
  return <SortableTrackRow {...props} />;
});

TrackRow.displayName = "TrackRow";

