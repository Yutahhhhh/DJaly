import { useCallback, useEffect, useRef, useState } from "react";
import type { Page } from "@/services/play";

export function usePagedResource<T>({ key, enabled = true, pageSize = 100, fetchPage, itemKey }: {
  key: string; enabled?: boolean; pageSize?: number; fetchPage: (offset: number, limit: number) => Promise<Page<T>>; itemKey: (item: T) => string | number;
}) {
  const [items, setItems] = useState<T[]>([]);
  const [total, setTotal] = useState(0);
  const [hasMore, setHasMore] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const generation = useRef(0);
  const itemsRef = useRef<T[]>([]);
  const loadingRef = useRef(false);
  const hasMoreRef = useRef(false);
  const nextOffsetRef = useRef(0);
  const errorRef = useRef<string | null>(null);
  const fetchRef = useRef(fetchPage);
  const itemKeyRef = useRef(itemKey);
  fetchRef.current = fetchPage;
  itemKeyRef.current = itemKey;

  const request = useCallback(async (offset: number, replace: boolean, requestGeneration: number) => {
    if (loadingRef.current) return;
    loadingRef.current = true; errorRef.current = null; setLoading(true); setError(null);
    try {
      const page = await fetchRef.current(offset, pageSize);
      if (generation.current !== requestGeneration) return;
      const prior = replace ? [] : itemsRef.current;
      const seen = new Set(prior.map(itemKeyRef.current));
      const unique = page.items.filter((item) => { const id = itemKeyRef.current(item); if (seen.has(id)) return false; seen.add(id); return true; });
      const next = [...prior, ...unique];
      const canContinue = page.has_more && page.items.length > 0;
      itemsRef.current = next; hasMoreRef.current = canContinue;
      nextOffsetRef.current = page.offset + page.items.length;
      setItems(next); setTotal(page.total); setHasMore(canContinue);
    } catch (cause) {
      if (generation.current === requestGeneration) { const message = cause instanceof Error ? cause.message : String(cause); errorRef.current = message; setError(message); }
    } finally {
      if (generation.current === requestGeneration) { loadingRef.current = false; setLoading(false); }
    }
  }, [pageSize]);

  useEffect(() => {
    const nextGeneration = ++generation.current;
    itemsRef.current = []; hasMoreRef.current = enabled; nextOffsetRef.current = 0; loadingRef.current = false; errorRef.current = null;
    setItems([]); setTotal(0); setHasMore(enabled); setError(null); setLoading(false);
    if (enabled) void request(0, true, nextGeneration);
    return () => { generation.current++; };
  }, [key, enabled, request]);

  const loadMore = useCallback(() => {
    if (!enabled || loadingRef.current || !hasMoreRef.current || errorRef.current) return;
    void request(nextOffsetRef.current, false, generation.current);
  }, [enabled, request]);
  const retry = useCallback(() => {
    if (loadingRef.current) return;
    void request(nextOffsetRef.current, itemsRef.current.length === 0, generation.current);
  }, [request]);
  const reload = useCallback(() => {
    const nextGeneration = ++generation.current;
    itemsRef.current = []; hasMoreRef.current = enabled; nextOffsetRef.current = 0; loadingRef.current = false; errorRef.current = null;
    setItems([]); setTotal(0); setHasMore(enabled); setError(null);
    if (enabled) void request(0, true, nextGeneration);
  }, [enabled, request]);

  const insert = useCallback((item: T) => {
    const id = itemKeyRef.current(item);
    if (itemsRef.current.some((existing) => itemKeyRef.current(existing) === id)) return;
    const next = [...itemsRef.current, item];
    itemsRef.current = next;
    setItems(next);
    setTotal((current) => current + 1);
  }, []);

  return { items, total, hasMore, loading, error, loadMore, retry, reload, insert };
}
