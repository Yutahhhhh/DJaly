import { useRef } from "react";
import type { CuePoint, Track } from "../types";
import { Waveform } from "./Waveform";
import { PhraseBar } from "./PhraseBar";
import { VocalTrack } from "./VocalTrack";
import { CueMarker } from "./CueMarker";

interface TimelineProps {
  track: Track;
  proposedCues?: CuePoint[];
  selectedCueId?: string | null;
  onSelectCue?: (cue: CuePoint) => void;
  onDragCue?: (cue: CuePoint, newPositionMs: number) => void;
  onAddCueAt?: (positionMs: number) => void;
  width?: number;
}

const WAVEFORM_H = 90;
const PHRASE_H = 26;
const VOCAL_H = 48;
const RULER_H = 20;
const TOTAL_H = WAVEFORM_H + PHRASE_H + VOCAL_H + RULER_H;

function formatTime(ms: number): string {
  const totalSec = Math.floor(ms / 1000);
  const min = Math.floor(totalSec / 60);
  const sec = totalSec % 60;
  return `${min}:${sec.toString().padStart(2, "0")}`;
}

/** Combines waveform + phrase + vocal + cue layers into one scrollable timeline. */
export function Timeline({
  track,
  proposedCues = [],
  selectedCueId,
  onSelectCue,
  onDragCue,
  onAddCueAt,
  width = 1400,
}: TimelineProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const durationMs = track.duration_ms;

  const rulerTicks: number[] = [];
  const tickIntervalMs = 15_000;
  for (let t = 0; t < durationMs; t += tickIntervalMs) {
    rulerTicks.push(t);
  }

  function handleBackgroundClick(e: React.MouseEvent<HTMLDivElement>) {
    if (!onAddCueAt) return;
    const rect = containerRef.current?.getBoundingClientRect();
    if (!rect) return;
    const relX = e.clientX - rect.left;
    const positionMs = (relX / width) * durationMs;
    onAddCueAt(Math.max(0, Math.min(durationMs, positionMs)));
  }

  return (
    <div className="timeline-scroll">
      <div
        ref={containerRef}
        className="timeline"
        style={{ width, height: TOTAL_H }}
        onDoubleClick={handleBackgroundClick}
      >
        <div className="timeline__layer" style={{ top: 0, height: WAVEFORM_H }}>
          <Waveform points={track.waveform ?? []} width={width} height={WAVEFORM_H} />
        </div>

        <div className="timeline__layer" style={{ top: WAVEFORM_H, height: PHRASE_H }}>
          <PhraseBar phrases={track.phrases} durationMs={durationMs} width={width} height={PHRASE_H} />
        </div>

        <div className="timeline__layer" style={{ top: WAVEFORM_H + PHRASE_H, height: VOCAL_H }}>
          <VocalTrack vocal={track.vocal_track} width={width} height={VOCAL_H} />
        </div>

        <div className="timeline__ruler" style={{ top: WAVEFORM_H + PHRASE_H + VOCAL_H, height: RULER_H, width }}>
          {rulerTicks.map((t) => (
            <span key={t} className="timeline__ruler-tick" style={{ left: (t / durationMs) * width }}>
              {formatTime(t)}
            </span>
          ))}
        </div>

        <svg className="timeline__cue-overlay" width={width} height={TOTAL_H - RULER_H}>
          {track.cues.map((cue) => (
            <CueMarker
              key={cue.id}
              cue={cue}
              durationMs={durationMs}
              width={width}
              height={TOTAL_H - RULER_H}
              variant="existing"
              selected={cue.id === selectedCueId}
              onSelect={onSelectCue}
              onDrag={onDragCue}
            />
          ))}
          {proposedCues.map((cue) => (
            <CueMarker
              key={`proposed-${cue.id}`}
              cue={cue}
              durationMs={durationMs}
              width={width}
              height={TOTAL_H - RULER_H}
              variant="proposed"
              selected={cue.id === selectedCueId}
              onSelect={onSelectCue}
            />
          ))}
        </svg>
      </div>
      <p className="timeline__hint">Double-click the timeline to add a cue at that position. Drag a marker's grip to reposition it.</p>
    </div>
  );
}
