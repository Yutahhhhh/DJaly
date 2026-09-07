import { useCallback, useEffect, useRef, useState } from "react";

import { performanceMetadataService } from "@/services/performance-metadata";
import type {
  PerformanceMetadata,
  PerformanceMetadataWrite,
} from "@/types/performance-metadata";


export function usePerformanceMetadata(trackId: number | null) {
  const [metadata, setMetadata] = useState<PerformanceMetadata | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const requestId = useRef(0);

  const reload = useCallback(async () => {
    const id = ++requestId.current;
    if (trackId === null) {
      setMetadata(null);
      setError(null);
      setLoading(false);
      return null;
    }
    setLoading(true);
    setError(null);
    try {
      const next = await performanceMetadataService.get(trackId);
      if (id === requestId.current) setMetadata(next);
      return next;
    } catch (cause) {
      if (id === requestId.current) setError(cause);
      throw cause;
    } finally {
      if (id === requestId.current) setLoading(false);
    }
  }, [trackId]);

  useEffect(() => {
    void reload().catch(() => undefined);
    return () => {
      requestId.current += 1;
    };
  }, [reload]);

  const replace = useCallback(async (
    changes: Omit<PerformanceMetadataWrite, "revision">,
  ) => {
    if (trackId === null || metadata === null) {
      throw new Error("Performance metadata must be loaded before it can be saved");
    }
    const id = requestId.current;
    setError(null);
    try {
      const next = await performanceMetadataService.replace(trackId, {
        ...changes,
        revision: metadata.revision,
      });
      if (id === requestId.current) setMetadata(next);
      return next;
    } catch (cause) {
      if (id === requestId.current) setError(cause);
      throw cause;
    }
  }, [metadata, trackId]);

  return { metadata, loading, error, reload, replace };
}
