import { useEffect, useState } from "react";
import { invoke, isTauri } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import { API_BASE_URL } from "@/services/api-client";

export type StartupProgress = {
  stage: string; label: string; completed: number; total: number; error?: string | null;
};
const initial: StartupProgress = {
  stage: "launch", label: "解析サービスを起動しています", completed: 0, total: 5,
};

export function useStartupProgress() {
  const [ready, setReady] = useState(false);
  const [progress, setProgress] = useState(initial);
  const [seconds, setSeconds] = useState(0);
  const [connectionError, setConnectionError] = useState("");
  const [retry, setRetry] = useState(0);
  useEffect(() => {
    if (ready) return;
    let live = true;
    let unsubscribe: (() => void) | undefined;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let request: AbortController | undefined;
    let startupEventReceived = false;
    const started = Date.now();
    setSeconds(0);
    const elapsed = setInterval(() => setSeconds(Math.floor((Date.now() - started) / 1000)), 1000);
    const accept = (value: StartupProgress) => {
      if (live) setProgress(value);
    };
    if (isTauri()) {
      void (async () => {
        const off = await listen<StartupProgress>("backend://startup", event => {
          startupEventReceived = true;
          accept(event.payload);
        });
        if (!live) { off(); return; }
        unsubscribe = off;
        const snapshot = await invoke<StartupProgress>("backend_startup_status");
        // A delayed snapshot must not replace a newer milestone event.
        if (!startupEventReceived) accept(snapshot);
      })().catch(cause => {
        if (live) setConnectionError(`起動状況の取得を再試行してください: ${String(cause)}`);
      });
    } else {
      setProgress({ ...initial, label: "解析サービスへの接続を確認しています" });
    }
    const checkServer = async () => {
      request = new AbortController();
      const deadline = setTimeout(() => request?.abort(), 3000);
      try {
        const response = await fetch(API_BASE_URL.replace(/\/api\/?$/, "/"), { signal: request.signal });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const data = await response.json();
        if (data.message !== "plumdeck Backend API is running") throw new Error("解析サービスの応答を確認できません");
        if (live) { setConnectionError(""); setReady(true); }
      } catch (cause) {
        if (live) {
          setConnectionError(`接続を再試行中: ${cause instanceof Error ? cause.message : String(cause)}`);
          timer = setTimeout(checkServer, 1000);
        }
      } finally {
        clearTimeout(deadline);
      }
    };
    void checkServer();
    return () => {
      live = false; clearInterval(elapsed); clearTimeout(timer); request?.abort(); unsubscribe?.();
    };
  }, [ready, retry]);
  return { ready, progress, seconds, connectionError, retry: () => setRetry(value => value + 1) };
}
