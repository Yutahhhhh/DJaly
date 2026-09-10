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
    const out = track.out_ms ?? (track.duration == null ? null : track.duration * 1000);
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
      className="flex-1 flex flex-col bg-muted/10 border-r min-w-0"
    >
      <div className="p-4 border-b bg-background flex justify-between items-center shadow-sm z-10">
        <h3 className="font-semibold">Current Setlist</h3>
        <div className="flex items-center gap-2 text-sm text-muted-foreground bg-muted px-2 py-1 rounded">
          <Clock className="h-4 w-4" />
          <span title="曲の全長合計">全長 {formatDuration(totalDuration)}</span>
          <span className="opacity-30">|</span>
          <span className={timingError ? "text-red-500" : ""} title={timingError ?? "IN/OUT・速度・重なりを反映"}>{timingError ? `予定 入力エラー: ${timingError}` : <>予定 {formatDuration(plannedDurationMs / 1000)}{unknownEntries ? ` + 未算出${unknownEntries}曲` : ""}</>}</span>
          {!timingError && targetDelta != null && <><span className="opacity-30">|</span><span className={targetDelta < 0 ? "text-red-500" : ""}>目標まで {targetDelta < 0 ? "超過 " : ""}{formatDuration(Math.abs(targetDelta))}</span></>}
          <span className="opacity-30">|</span><span>{tracks.length} tracks</span>
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
                  <div className="ml-7 grid grid-cols-5 gap-2 rounded border bg-background/70 p-2 text-xs">
                    <label>IN 秒<input className="mt-1 w-full rounded border bg-background px-1 py-1" type="number" min="0" step="0.1" defaultValue={(track.in_ms || 0) / 1000} key={`in-${track.revision}`} onBlur={(event) => onTimingChange(index, { in_ms: Number(event.currentTarget.value) * 1000 })} /></label>
                    <label>OUT 秒<input className="mt-1 w-full rounded border bg-background px-1 py-1" type="number" min="0" step="0.1" placeholder={String(track.duration ?? "—")} defaultValue={track.out_ms == null ? "" : track.out_ms / 1000} key={`out-${track.revision}`} onBlur={(event) => onTimingChange(index, { out_ms: event.currentTarget.value === "" ? null : Number(event.currentTarget.value) * 1000 })} /></label>
                    <label>速度倍率<input className="mt-1 w-full rounded border bg-background px-1 py-1" type="number" min="0.01" step="0.01" defaultValue={track.playback_rate || 1} key={`rate-${track.revision}`} onBlur={(event) => onTimingChange(index, { playback_rate: Number(event.currentTarget.value) })} /></label>
                    <label>追加 秒<input className="mt-1 w-full rounded border bg-background px-1 py-1" type="number" min="0" step="0.1" defaultValue={(track.extra_duration_ms || 0) / 1000} key={`extra-${track.revision}`} onBlur={(event) => onTimingChange(index, { extra_duration_ms: Number(event.currentTarget.value) * 1000 })} /></label>
                    <label>次曲と重ねる 秒<input className="mt-1 w-full rounded border bg-background px-1 py-1" type="number" min="0" step="0.1" disabled={index === tracks.length - 1} defaultValue={(track.overlap_next_ms || 0) / 1000} key={`overlap-${track.revision}`} onBlur={(event) => onTimingChange(index, { overlap_next_ms: Number(event.currentTarget.value) * 1000 })} /></label>
                  </div>
                </Fragment>
              ))}
            </SortableContext>
          )}
        </div>
      </ScrollArea>
    </div>
  );
}
