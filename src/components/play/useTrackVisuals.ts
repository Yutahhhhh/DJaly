import { useEffect, useState } from "react";
import { metadataService, type FileMetadata } from "@/services/metadata";

// Share metadata between deck lanes/covers and visible browser rows, at bounded concurrency.
const cache = new Map<number, Promise<FileMetadata>>();
let active = 0;
const waiting: (() => void)[] = [];
function fetchVisuals(id: number): Promise<FileMetadata> {
  const cached = cache.get(id);
  if (cached) return cached;
  const request = new Promise<FileMetadata>((resolve, reject) => {
    const begin = () => {
      active++;
      void metadataService.getMetadata(id).then(resolve, reject).finally(() => { active--; waiting.shift()?.(); });
    };
    if (active < 4) begin(); else waiting.push(begin);
  });
  cache.set(id, request);
  if (cache.size > 160) cache.delete(cache.keys().next().value!);
  void request.catch(() => cache.delete(id));
  return request;
}

export function useTrackVisuals(trackId: number | null) {
  const [result, setResult] = useState<{ id: number | null; data: FileMetadata | null; loading: boolean }>({ id: null, data: null, loading: false });
  useEffect(() => {
    let live = true;
    if (!trackId) { setResult({ id: null, data: null, loading: false }); return; }
    setResult({ id: trackId, data: null, loading: true });
    void fetchVisuals(trackId).then((data) => { if (live) setResult({ id: trackId, data, loading: false }); })
      .catch(() => { if (live) setResult({ id: trackId, data: null, loading: false }); });
    return () => { live = false; };
  }, [trackId]);
  return result.id === trackId ? result : { id: trackId, data: null, loading: Boolean(trackId) };
}

export function artworkUrl(artwork: string) {
  return artwork.startsWith("data:") ? artwork : `data:image/jpeg;base64,${artwork}`;
}
