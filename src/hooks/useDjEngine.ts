import { useCallback, useEffect, useRef, useState } from "react";

import { djEngineClient, DjEngineCommandError } from "@/services/dj-engine/client";
import type { EngineClientState, EngineStatus } from "@/types/dj-engine";

/**
 * ネイティブ DJ エンジン（Phase 0 シミュレータ）に接続するためのフック。
 *
 * 既存の `<audio>` プレビュー再生とは独立している。エンジンが
 * 未インストール・未起動でも例外は投げず、`status.installed` /
 * `status.running` を見て UI 側で素直に劣化させる。
 *
 * 自動起動はしない。`start()` を明示的に呼んだときだけ起動する。
 */
export function useDjEngine() {
  const [status, setStatus] = useState<EngineStatus | null>(null);
  const [engineState, setEngineState] = useState<EngineClientState>(
    djEngineClient.getState()
  );
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [resyncAttempt, setResyncAttempt] = useState(0);
  const resyncing = useRef(false);

  const refreshStatus = useCallback(async () => {
    const next = await djEngineClient.status();
    setStatus(next);
    return next;
  }, []);

  useEffect(() => {
    let cancelled = false;
    const unsubscribeState = djEngineClient.subscribe((next) => {
      if (!cancelled) setEngineState(next);
    });
    const unsubscribeStatus = djEngineClient.subscribeStatus((next) => {
      if (!cancelled) setStatus(next);
    });
    void refreshStatus();
    return () => {
      cancelled = true;
      unsubscribeState();
      unsubscribeStatus();
    };
  }, [refreshStatus]);

  // イベントを取りこぼした / セッションが失効したらスナップショットを取り直す。
  useEffect(() => {
    const needsResync =
      engineState.droppedEvents > 0 || engineState.sessionInvalidated;
    if (!needsResync || resyncing.current) return;

    let cancelled = false;
    let retryTimer: ReturnType<typeof setTimeout> | undefined;
    resyncing.current = true;
    void (async () => {
      try {
        if (engineState.sessionInvalidated) {
          await djEngineClient.connect();
        } else {
          await djEngineClient.refreshSnapshot();
        }
        if (!cancelled) {
          setError(null);
          setResyncAttempt(0);
        }
      } catch (resyncError) {
        if (!cancelled) {
          setError(toMessage(resyncError));
          const delayMs = Math.min(1_000 * 2 ** Math.min(resyncAttempt, 3), 10_000);
          retryTimer = setTimeout(() => setResyncAttempt((attempt) => attempt + 1), delayMs);
        }
      } finally {
        resyncing.current = false;
      }
    })();
    return () => {
      cancelled = true;
      if (retryTimer) clearTimeout(retryTimer);
    };
  }, [engineState.droppedEvents, engineState.sessionInvalidated, resyncAttempt]);

  const run = useCallback(
    async <T,>(task: () => Promise<T>): Promise<T | null> => {
      setBusy(true);
      setError(null);
      try {
        return await task();
      } catch (taskError) {
        setError(toMessage(taskError));
        return null;
      } finally {
        setBusy(false);
      }
    },
    []
  );

  const start = useCallback(
    (outputDevice?: string) => run(async () => {
      const next = await djEngineClient.start(outputDevice);
      setStatus(next);
      if (next.running) {
        await djEngineClient.connect();
      }
      return next;
    }),
    [run]
  );

  const stop = useCallback(
    () => run(async () => {
      const next = await djEngineClient.stop();
      setStatus(next);
      return next;
    }),
    [run]
  );

  const connect = useCallback(
    () => run(() => djEngineClient.connect()),
    [run]
  );

  return {
    /** null は状態取得前。 */
    status,
    state: engineState,
    error,
    busy,
    client: djEngineClient,
    start,
    stop,
    connect,
    refreshStatus,
  };
}

function toMessage(error: unknown): string {
  if (error instanceof DjEngineCommandError) return error.message;
  if (error instanceof Error) return error.message;
  return String(error);
}
