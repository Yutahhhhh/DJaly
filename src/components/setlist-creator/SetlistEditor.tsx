import { useState } from "react";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Track } from "@/types";
import type { SetlistTrack } from "@/services/setlists";
import { Clock } from "lucide-react";
import { formatDuration } from "@/lib/utils";
import {
  SortableContext,
  verticalListSortingStrategy,
} from "@dnd-kit/sortable";
import { TrackRow } from "./TrackRow";
import { WordplayBridge } from "./WordplayBridge";
import { useDroppable } from "@dnd-kit/core";
import { Fragment } from "react/jsx-runtime";

export interface SetlistEditorProps {
  tracks: SetlistTrack[];
  onRemoveTrack: (index: number) => void;
  onTrackSelect: (track: Track) => void;
  selectedTrackId: number | null;
  onDeleteWordplay?: (setlistTrackId: number) => void;
  onTimingChange: (index: number, change: Partial<SetlistTrack>) => void;
  targetDurationSeconds?: number | null;
}

export function SetlistEditor({
  tracks,
  onRemoveTrack,
  onTrackSelect,
  selectedTrackId,
  onDeleteWordplay,
  onTimingChange,
  targetDurationSeconds,
}: SetlistEditorProps) {
  const [showTiming, setShowTiming] = useState(false);
  const { setNodeRef } = useDroppable({ id: "setlist-editor-droppable" });
  const totalDuration = tracks.reduce(
    (acc: number, t: Track) => acc + (t.duration || 0),
    0
  );
  let plannedDurationMs = 0;
  let unknownEntries = 0;
  let timingError: string | null = null;
  const entryDurations: Array<number | null> = [];
  tracks.forEach((track, index) => {
    const out = track.out_ms ?? Math.min(track.duration == null ? Infinity : track.duration * 1000, (track.in_ms ?? 0) + 120_000 * (track.playback_rate ?? 1));
    const input = track.in_ms ?? 0; const rate = track.playback_rate ?? 1; const extra = track.extra_duration_ms ?? 0;
    if (out == null) { unknownEntries += 1; entryDurations.push(null); }
    else if (![out, input, rate, extra].every(Number.isFinite) || input < 0 || out <= input || rate <= 0 || extra < 0 || track.duration != null && out > track.duration * 1000 + 0.5) {
      timingError ??= `${index + 1}曲目のIN/OUT・速度・追加時間を確認してください`;
      entryDurations.push(null);
    } else {
      const duration = (out - input) / rate + extra;
      entryDurations.push(duration); plannedDurationMs += duration;
    }
  });
  tracks.slice(0, -1).forEach((track, index) => {
    const overlap = track.overlap_next_ms ?? 0; const left = entryDurations[index]; const right = entryDurations[index + 1];
    if (!Number.isFinite(overlap) || overlap < 0 || overlap > 0 && (left == null || right == null || overlap > Math.min(left, right) + 0.5)) timingError ??= `${index + 1}曲目の重なりが隣接する予定時間を超えています`;
    else plannedDurationMs -= overlap;
  });
  const targetDelta = targetDurationSeconds == null ? null : targetDurationSeconds - plannedDurationMs / 1000;

  return (
    <div
      ref={setNodeRef}
      className="setlist-editor flex-1 flex flex-col bg-muted/10 min-w-0 min-h-0"
    >
      <div className="border-b bg-background px-3 py-3 space-y-2 shrink-0">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h3 className="text-sm font-semibold">Current Setlist <span className="text-xs font-normal text-muted-foreground">· {tracks.length}曲</span></h3>
          <button type="button" className="rounded border px-2 py-1 text-xs" aria-expanded={showTiming} onClick={() => setShowTiming(value => !value)}>{showTiming ? "使用時間を閉じる" : "使用時間を編集"}</button>
        </div>
        <div className="setlist-summary">
          <span className="inline-flex items-center gap-1"><Clock className="h-3 w-3" />予定 {formatDuration(plannedDurationMs / 1000)}</span>
          {targetDurationSeconds != null && <span>目標 {formatDuration(targetDurationSeconds)}</span>}
          {!timingError && targetDelta != null && <span className={targetDelta < 0 ? "text-red-500" : ""}>{targetDelta < 0 ? "超過" : "残り"} {formatDuration(Math.abs(targetDelta))}</span>}
          <span title="音源の全長合計">全長 {formatDuration(totalDuration)}</span>
        </div>
        {showTiming && <p className="text-xs text-muted-foreground">未指定は1曲2分（短い曲は全長）。保存済みの指定は保持します。</p>}
        {timingError && <p role="alert" className="text-xs text-red-500">{timingError}</p>}
        {unknownEntries > 0 && <p className="text-xs text-muted-foreground">未算出 {unknownEntries}曲</p>}
      </div>

      <ScrollArea className="flex-1 min-h-0">
        <div className="p-4 space-y-2 pb-20">
          {tracks.length === 0 ? (
            <div className="h-64 flex flex-col items-center justify-center text-muted-foreground border-2 border-dashed rounded-lg">
              <p className="text-sm">Drag tracks here from the library</p>
            </div>
          ) : (
            <SortableContext
              items={tracks.map((t) => `setlist-entry-${t.setlist_track_id}`)}
              strategy={verticalListSortingStrategy}
            >
              {tracks.map((track: any, index: number) => (
                <Fragment key={`group-${track.setlist_track_id}`}>
                  {/* ワードプレイ・ブリッジの表示判定 */}
                  {track.wordplay_json && index > 0 && (
                    <WordplayBridge
                      data={track.wordplay_json}
                      fromTrackPath={tracks[index - 1]?.filepath}
                      toTrackPath={track.filepath}
                      onDelete={
                        onDeleteWordplay && track.setlist_track_id
                          ? () => onDeleteWordplay(track.setlist_track_id)
                          : undefined
                      }
                    />
                  )}

                  <TrackRow
                    id={`setlist-entry-${track.setlist_track_id}`}
                    track={track}
                    type="SETLIST_ITEM"
                    isSelected={selectedTrackId === track.id}
                    onSelect={() => onTrackSelect(track)}
                    onRemove={() => onRemoveTrack(index)}
                  />
                  {showTiming && <div className="ml-7 flex flex-wrap items-center gap-2 rounded border bg-background/70 p-2 text-xs">
                    <label className="flex items-center gap-2 whitespace-nowrap">使用時間（分）
                      <input className="w-20 rounded border bg-background px-2 py-1" type="number" min="0.01" step="0.1"
                        defaultValue={Number(((entryDurations[index] ?? 120_000) / 60_000).toFixed(2))}
                        key={`duration-${track.setlist_track_id}-${track.revision}`}
                        onBlur={(event) => {
                          const minutes = Number(event.currentTarget.value);
                          if (!event.currentTarget.value || !Number.isFinite(minutes) || minutes <= 0) { event.currentTarget.value = String(Number(((entryDurations[index] ?? 120_000) / 60_000).toFixed(2))); return; }
                          if (Math.abs(minutes * 60_000 - (entryDurations[index] ?? 120_000)) < 600) return;
                          onTimingChange(index, { out_ms: Math.min(track.duration == null ? Infinity : track.duration * 1000, (track.in_ms ?? 0) + minutes * 60_000 * (track.playback_rate ?? 1)), extra_duration_ms: 0 });
                        }} />
                    </label>
                  </div>}
                </Fragment>
              ))}
            </SortableContext>
          )}
        </div>
      </ScrollArea>
    </div>
  );
}
