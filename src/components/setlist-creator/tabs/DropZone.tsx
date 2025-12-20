import { cn } from "@/lib/utils";
import { useDroppable } from "@dnd-kit/core";

export function DropZone({ id, label, track, className }: any) {
  const { setNodeRef, isOver } = useDroppable({
    id,
    data: { type: "DROP_ZONE" },
  });

  return (
    <div
      ref={setNodeRef}
      className={cn(
        "flex flex-col items-center justify-center p-2 rounded-md border-2 border-dashed transition-all duration-300",
        "w-40 h-28 pointer-events-auto relative overflow-hidden",
        isOver
          ? "border-primary bg-primary/20 scale-105 shadow-lg"
          : "border-border bg-muted/20",
        className
      )}
    >
      <div
        className={cn(
          "absolute inset-0 bg-primary/5 opacity-0 transition-opacity",
          isOver && "opacity-100 animate-pulse"
        )}
      />

      <span className="text-[10px] text-muted-foreground font-bold mb-1 uppercase tracking-wider relative z-10">
        {label}
      </span>

      <div className="relative z-10 w-full flex flex-col items-center">
        {track ? (
          <div className="text-xs font-medium text-center w-full px-1 animate-in zoom-in-95">
            <div className="truncate text-primary font-bold">{track.title}</div>
            <div className="truncate text-[10px] text-muted-foreground">
              {track.artist}
            </div>
          </div>
        ) : (
          <div className="text-[10px] text-muted-foreground/40 text-center leading-tight">
            {isOver ? (
              <span className="text-primary font-bold">Release to set</span>
            ) : (
              <>
                Drag track
                <br />
                here
              </>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
