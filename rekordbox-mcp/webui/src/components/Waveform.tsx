import type { WaveformPoint } from "../types";

interface WaveformProps {
  points: WaveformPoint[];
  width: number;
  height: number;
}

/** Color waveform rendered as vertical bars, djcues-style (RGB = bass/mid/treble). */
export function Waveform({ points, width, height }: WaveformProps) {
  if (!points.length) {
    return (
      <svg width={width} height={height} className="waveform waveform--empty">
        <text x={width / 2} y={height / 2} textAnchor="middle" className="waveform__empty-text">
          No waveform data
        </text>
      </svg>
    );
  }

  const barWidth = width / points.length;
  const mid = height / 2;

  return (
    <svg width={width} height={height} className="waveform" preserveAspectRatio="none">
      <rect x={0} y={0} width={width} height={height} className="waveform__bg" />
      {points.map((p, i) => {
        const barHeight = Math.max(1, p.height * (height - 2));
        const r = Math.round((Math.min(p.red, 7) / 7) * 255);
        const g = Math.round((Math.min(p.green, 7) / 7) * 255);
        const b = Math.round((Math.min(p.blue, 7) / 7) * 255);
        return (
          <rect
            key={i}
            x={i * barWidth}
            y={mid - barHeight / 2}
            width={Math.max(1, barWidth - 0.3)}
            height={barHeight}
            fill={`rgb(${r},${g},${b})`}
          />
        );
      })}
    </svg>
  );
}
