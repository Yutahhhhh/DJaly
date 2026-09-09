import { useEffect, useState } from "react";
import { apiClient } from "@/services/api-client";

export type WaveformDetail = {
  bins_per_second: number; duration_ms: number; amplitude_scale: number;
  peaks: number[]; low: number[]; mid: number[]; high: number[];
};

// Deck lanes ask for the full 300 bins/sec; list rows ask for a few hundred
// bins, which is ~6KB instead of ~1MB. Cache and gate them separately so a
// scrolling browser cannot starve the decks or flood the backend.
const cache = new Map<string, { request: Promise<WaveformDetail>; fetchedAt: number }>();
let active = 0;
const waiting: (() => void)[] = [];
function fetchDetail(id: number, bins?: number) {
  const key = `${id}:${bins ?? "full"}`;
  const existing = cache.get(key);
  if (existing && Date.now() - existing.fetchedAt < 5 * 60_000) return existing.request;
  const request = new Promise<WaveformDetail>((resolve, reject) => {
    const begin = () => {
      active++;
      void apiClient.get<WaveformDetail>(`/play/tracks/${id}/waveform-detail`, bins ? { bins } : undefined)
        .then(resolve, reject).finally(() => { active--; waiting.shift()?.(); });
    };
    if (active < 4) begin(); else waiting.push(begin);
  });
  cache.set(key, { request, fetchedAt: Date.now() });
  // Reduced payloads are small, so a browser page's worth can stay resident.
  const limit = bins ? 240 : 8;
  while (cache.size > limit) {
    const oldest = cache.keys().next().value;
    if (oldest === undefined || oldest === key) break;
    cache.delete(oldest);
  }
  void request.catch(() => { if (cache.get(key)?.request === request) cache.delete(key); });
  return request;
}

export function useWaveformDetail(trackId: number | null, bins?: number) {
  const [revision, setRevision] = useState(0);
  const [result, setResult] = useState<{ id: number | null; data: WaveformDetail | null; loading: boolean; error: string | null }>({ id: null, data: null, loading: false, error: null });
  useEffect(() => {
    let live = true;
    if (trackId === null) { setResult({ id: null, data: null, loading: false, error: null }); return; }
    setResult({ id: trackId, data: null, loading: true, error: null });
    void fetchDetail(trackId, bins).then((data) => {
      if (live) setResult({ id: trackId, data, loading: false, error: null });
    }, (error: unknown) => {
      if (live) setResult({ id: trackId, data: null, loading: false, error: error instanceof Error ? error.message : "詳細波形を取得できませんでした。" });
    });
    return () => { live = false; };
  }, [trackId, bins, revision]);
  const state = result.id === trackId ? result : { id: trackId, data: null, loading: trackId !== null, error: null };
  return { ...state, retry: () => { if (trackId !== null) cache.delete(`${trackId}:${bins ?? "full"}`); setRevision((value) => value + 1); } };
}
