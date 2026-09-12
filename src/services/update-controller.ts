import type { DownloadEvent } from "@tauri-apps/plugin-updater";

export type UpdateHandle = {
  version: string; currentVersion: string; body?: string;
  download: (onEvent: (event: DownloadEvent) => void) => Promise<void>;
  install: () => Promise<void>; close: () => Promise<void>;
};
export type UpdateState = {
  phase: "idle" | "checking" | "latest" | "available" | "downloading" | "installing" | "ready" | "error";
  currentVersion: string; version?: string; notes?: string; error?: string;
  downloaded: number; total?: number;
};

/** One operation across automatic checks, toolbar clicks and StrictMode mounts. */
export function createUpdateController(deps: {
  currentVersion: string;
  check: () => Promise<UpdateHandle | null>;
  activeSession: () => Promise<boolean>;
  relaunch: () => Promise<void>;
}) {
  let state: UpdateState = { phase: "idle", currentVersion: deps.currentVersion, downloaded: 0 };
  let handle: UpdateHandle | null = null;
  let downloaded = false;
  let automaticChecked = false;
  let task: Promise<void> | null = null;
  const listeners = new Set<() => void>();
  const set = (patch: Partial<UpdateState>) => {
    state = { ...state, ...patch }; listeners.forEach(listener => listener());
  };
  const run = (action: () => Promise<void>) => {
    if (task) return task;
    task = Promise.resolve().then(action).finally(() => { task = null; });
    return task;
  };
  const check = () => run(async () => {
    if (state.phase === "ready") return;
    set({ phase: "checking", error: undefined, downloaded: 0, total: undefined });
    try {
      await handle?.close(); handle = null; downloaded = false;
      handle = await deps.check();
      if (handle) set({ phase: "available", version: handle.version, currentVersion: handle.currentVersion, notes: handle.body });
      else set({ phase: "latest", version: undefined, notes: undefined });
    } catch (cause) {
      set({ phase: "error", error: `更新を確認できませんでした: ${String(cause)}` });
    }
  });
  const blocked = async () => {
    if (!await deps.activeSession()) return false;
    set({ error: "Junctionセッションを終了してから更新・再起動してください。" });
    return true;
  };
  const restart = async () => {
    try {
      if (await blocked()) return;
      await deps.relaunch();
    } catch (cause) {
      set({ phase: "ready", error: `更新はインストール済みです。再起動を再試行してください: ${String(cause)}` });
    }
  };
  const install = () => run(async () => {
    if (!handle || state.phase === "ready") return;
    set({ error: undefined });
    try {
      if (await blocked()) return;
      if (!downloaded) {
        set({ phase: "downloading", downloaded: 0, total: undefined });
        await handle.download(event => {
          if (event.event === "Started") set({ total: event.data.contentLength, downloaded: 0 });
          if (event.event === "Progress") set({ downloaded: state.downloaded + event.data.chunkLength });
        });
        downloaded = true;
      }
      // A session can start while a long download is in progress.
      if (await blocked()) { set({ phase: "available" }); return; }
      set({ phase: "installing" });
      await handle.install();
      set({ phase: "ready" });
      await restart();
    } catch (cause) {
      set({ phase: "available", error: `更新を適用できませんでした: ${String(cause)}` });
    }
  });
  return {
    getSnapshot: () => state,
    subscribe: (listener: () => void) => { listeners.add(listener); return () => { listeners.delete(listener); }; },
    check, install,
    restart: () => run(restart),
    automaticCheck: () => {
      if (automaticChecked) return task ?? Promise.resolve();
      automaticChecked = true;
      return check();
    },
  };
}
