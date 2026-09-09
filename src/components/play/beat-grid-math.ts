import type { PerformanceBeatGrid } from "../../types/performance-metadata";

export function lowerBeat(times: number[], ms: number) {
  let low = 0, high = times.length;
  while (low < high) { const mid = (low + high) >>> 1; if (times[mid] < ms) low = mid + 1; else high = mid; }
  return low;
}

export function barNumbers(count: number, numbers: number[] | undefined, meter: number) {
  let bar = numbers?.[0] === 1 || !numbers ? 0 : 1;
  return Array.from({ length: count }, (_, i) => { if ((numbers?.[i] ?? i % meter + 1) === 1) bar++; return bar; });
}

export function nearestBeat(grid: PerformanceBeatGrid, ms: number) {
  const times = grid.beat_times_ms;
  if (times?.length) {
    const right = Math.min(times.length - 1, lowerBeat(times, ms)), left = Math.max(0, right - 1);
    return Math.abs(times[left] - ms) <= Math.abs(times[right] - ms) ? times[left] : times[right];
  }
  return grid.first_beat_ms + Math.round((ms - grid.first_beat_ms) * grid.bpm / 60000) * 60000 / grid.bpm;
}

function transform(grid: PerformanceBeatGrid, fn: (ms: number) => number, duration: number): PerformanceBeatGrid {
  const times = grid.beat_times_ms;
  if (times?.length) {
    const entries = times.map((ms, i) => ({ ms: fn(ms), beat: grid.beat_numbers?.[i] ?? i % grid.beats_per_bar + 1 })).filter(({ ms }) => ms >= 0 && ms < duration);
    if (entries.length < 2) throw new Error("曲内に2拍以上残る範囲で調整してください");
    return { ...grid, first_beat_ms: entries[0].ms, beat_times_ms: entries.map(x => x.ms), beat_numbers: entries.map(x => x.beat), source: "manual", confidence: null };
  }
  const first = fn(grid.first_beat_ms);
  // Equivalent bar origin, preserving the grid when shifting left past zero.
  const barMs = 60000 / grid.bpm * grid.beats_per_bar;
  const origin = first < 0 ? first + Math.ceil(-first / barMs) * barMs : first;
  if (origin >= duration) throw new Error("基準拍が曲の範囲外です");
  return { ...grid, first_beat_ms: origin, source: "manual", confidence: null };
}

export function shiftGrid(grid: PerformanceBeatGrid, deltaMs: number, duration: number) {
  return transform(grid, ms => ms + deltaMs, duration);
}

export function scaleGrid(grid: PerformanceBeatGrid, bpm: number, anchorMs: number, duration: number) {
  if (!Number.isFinite(bpm) || bpm < 20 || bpm > 300) throw new Error("BPMは20〜300で指定してください");
  const ratio = grid.bpm / bpm;
  return transform({ ...grid, bpm }, ms => anchorMs + (ms - anchorMs) * ratio, duration);
}

export function setDownbeat(grid: PerformanceBeatGrid, ms: number, duration: number) {
  const shifted = shiftGrid(grid, ms - nearestBeat(grid, ms), duration);
  const times = shifted.beat_times_ms;
  if (!times?.length) return { ...shifted, first_beat_ms: ms };
  const index = Math.min(times.length - 1, lowerBeat(times, ms - 0.001));
  return { ...shifted, beat_numbers: times.map((_, i) => ((i - index) % grid.beats_per_bar + grid.beats_per_bar) % grid.beats_per_bar + 1) };
}

export function subdivideGrid(grid: PerformanceBeatGrid, factor: 0.5 | 2, anchor: number): PerformanceBeatGrid {
  const bpm = grid.bpm * factor;
  if (bpm < 20 || bpm > 300) throw new Error("BPMは20〜300で指定してください");
  const times = grid.beat_times_ms;
  if (!times?.length) return { ...grid, bpm, first_beat_ms: nearestBeat(grid, anchor), source: "manual", confidence: null };
  const anchorTime = nearestBeat(grid, anchor), anchorIndex = times.indexOf(anchorTime);
  const next = factor === 2 ? times.flatMap((ms, i) => i + 1 < times.length ? [ms, (ms + times[i + 1]) / 2] : [ms]) : times.filter((_, i) => (i - anchorIndex) % 2 === 0);
  if (next.length < 2) throw new Error("2拍以上必要です");
  const nextAnchor = next.indexOf(anchorTime);
  return { ...grid, bpm, first_beat_ms: next[0], beat_times_ms: next, beat_numbers: next.map((_, i) => ((i - nextAnchor) % grid.beats_per_bar + grid.beats_per_bar) % grid.beats_per_bar + 1), source: "manual", confidence: null };
}
