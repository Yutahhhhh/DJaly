import type { Phrase } from "../types";

interface PhraseBarProps {
  phrases: Phrase[];
  durationMs: number;
  width: number;
  height: number;
}

const LABEL_COLORS: Record<string, string> = {
  Intro: "#3b5a7a",
  Up: "#3d7a4f",
  Down: "#7a5a3d",
  Chorus: "#c0392b",
  Verse1: "#5b3d7a",
  Verse2: "#5b3d7a",
  Verse3: "#5b3d7a",
  Verse4: "#5b3d7a",
  Verse5: "#5b3d7a",
  Verse6: "#5b3d7a",
  Bridge: "#7a6a3d",
  Outro: "#3d6a7a",
  Unknown: "#4a4a4a",
};

/** Renders PSSI phrase sections as labeled colored blocks along the timeline. */
export function PhraseBar({ phrases, durationMs, width, height }: PhraseBarProps) {
  if (!phrases.length || durationMs <= 0) {
    return <div className="phrase-bar phrase-bar--empty" style={{ width, height }} />;
  }

  return (
    <svg width={width} height={height} className="phrase-bar" preserveAspectRatio="none">
      {phrases.map((phrase, i) => {
        const x = (phrase.position_ms / durationMs) * width;
        const w = Math.max(1, (phrase.duration_ms / durationMs) * width);
        const color = LABEL_COLORS[phrase.label] ?? "#4a4a4a";
        return (
          <g key={i}>
            <rect x={x} y={0} width={w} height={height} fill={color} stroke="#111" strokeWidth={0.5} />
            {w > 28 && (
              <text
                x={x + w / 2}
                y={height / 2 + 4}
                textAnchor="middle"
                className="phrase-bar__label"
              >
                {phrase.label}
              </text>
            )}
          </g>
        );
      })}
    </svg>
  );
}
