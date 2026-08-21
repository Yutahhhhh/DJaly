import type { CuePoint } from "../types";

interface CueMarkerProps {
  cue: CuePoint;
  durationMs: number;
  width: number;
  height: number;
  variant: "existing" | "proposed";
  selected?: boolean;
  onSelect?: (cue: CuePoint) => void;
  onDrag?: (cue: CuePoint, newPositionMs: number) => void;
}

const HOT_CUE_COLORS = [
  "#e0e0e0", // memory (kind 0)
  "#2ecc71", // A
  "#3498db", // B
  "#f1c40f", // C
  "#e74c3c", // D
  "#1abc9c", // E
  "#e67e22", // F
  "#9b59b6", // G
  "#ff5fa2", // H
];

function labelFor(cue: CuePoint): string {
  if (cue.comment) return cue.comment;
  if (cue.kind === 0) return "Memory";
  return `Hot ${cue.kind}`;
}

/** A single draggable cue marker line + flag, overlaid on the timeline. */
export function CueMarker({
  cue,
  durationMs,
  width,
  height,
  variant,
  selected,
  onSelect,
  onDrag,
}: CueMarkerProps) {
  if (durationMs <= 0) return null;
  const x = (cue.position_ms / durationMs) * width;
  const color = HOT_CUE_COLORS[cue.kind] ?? "#e0e0e0";
  const isLoop = cue.loop_end_ms != null;
  const loopEndX = isLoop ? (cue.loop_end_ms! / durationMs) * width : null;

  function handlePointerDown(e: React.PointerEvent<SVGGElement>) {
    if (!onDrag) {
      onSelect?.(cue);
      return;
    }
    e.stopPropagation();
    const svg = (e.target as SVGElement).ownerSVGElement;
    if (!svg) return;
    const rect = svg.getBoundingClientRect();

    function handleMove(ev: PointerEvent) {
      const relX = Math.min(Math.max(ev.clientX - rect.left, 0), width);
      const newMs = (relX / width) * durationMs;
      onDrag!(cue, newMs);
    }
    function handleUp() {
      window.removeEventListener("pointermove", handleMove);
      window.removeEventListener("pointerup", handleUp);
    }
    window.addEventListener("pointermove", handleMove);
    window.addEventListener("pointerup", handleUp);
    onSelect?.(cue);
  }

  return (
    <g
      className={`cue-marker cue-marker--${variant}${selected ? " cue-marker--selected" : ""}`}
      onPointerDown={handlePointerDown}
    >
      {isLoop && loopEndX !== null && (
        <rect
          x={Math.min(x, loopEndX)}
          y={0}
          width={Math.abs(loopEndX - x)}
          height={height}
          fill={color}
          opacity={0.15}
        />
      )}
      <line
        x1={x}
        y1={0}
        x2={x}
        y2={height}
        stroke={color}
        strokeWidth={selected ? 3 : 2}
        strokeDasharray={variant === "proposed" ? "4,3" : undefined}
      />
      <rect x={x - 2} y={0} width={4} height={10} fill={color} className="cue-marker__grip" />
      <text x={x + 4} y={12} className="cue-marker__label" fill={color}>
        {labelFor(cue)}
      </text>
    </g>
  );
}
