import React from "react";
import { Button } from "@/components/ui/button";
import { GripVertical, X, Plus } from "lucide-react";
import { Track } from "@/types";
import { useSortable } from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { TrackRow as BaseTrackRow } from "@/components/track-row";
import { cn } from "@/lib/utils";

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
  return (
    <div className="relative group/row w-full">
      <BaseTrackRow
        track={track}
        viewType="list"
        isSelected={isSelected}
        onClick={onSelect}
        innerRef={innerRef}
        style={style}
        className={cn(
          "transition-all",
          isDragging ? "opacity-20 border-primary bg-primary/5" : "",
          isSelected ? "bg-primary/5" : ""
        )}
        showMeta={true}
        prefix={
          <div className="flex items-center gap-1 shrink-0 z-20">
            {dragHandleProps ? (
              <div
                {...dragHandleProps}
                className="cursor-grab active:cursor-grabbing p-1 text-muted-foreground/30 hover:text-foreground transition-colors"
              >
                <GripVertical className="h-4 w-4" />
              </div>
            ) : (
              <div className="w-2" />
            )}
          </div>
        }
        suffix={
          <div className="flex gap-1 shrink-0 z-20 ml-2">
            {onAdd && (
              <Button
                variant="ghost"
                size="icon"
                className="h-7 w-7 text-primary hover:bg-primary/10"
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
                className="h-7 w-7 opacity-0 group-hover/row:opacity-100 text-muted-foreground hover:text-destructive transition-opacity"
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
