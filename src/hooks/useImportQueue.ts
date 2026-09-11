import { useEffect, useState } from "react";
import { WS_BASE_URL } from "@/services/api-client";
import { workflowsService, type ImportBatch } from "@/services/workflows";

export const importFinished = (batch: ImportBatch) =>
  ["completed", "completed_with_errors", "canceled"].includes(batch.state);

/** App-scoped observer. DB snapshots, not component-local job IDs, are authoritative. */
export function useImportQueue() {
  const [batches, setBatches] = useState<ImportBatch[]>([]);
  const [error, setError] = useState("");
  useEffect(() => {
    let live = true;
    let socket: WebSocket | undefined;
    let reconnect: ReturnType<typeof setTimeout>;
    let lastSnapshot = 0;
    let pending = false;
    let generation = 0;
    let previous: Map<string, number> | null = null;
    const accept = (rows: ImportBatch[]) => {
      if (!live) return;
      const next = new Map(rows.map(row => [row.id, Number(row.succeeded_items)]));
      if (previous && rows.some(row => Number(row.succeeded_items) > (previous?.get(row.id) ?? 0))) {
        window.dispatchEvent(new Event("plumdeck:import-tracks-updated"));
      }
      previous = next;
      generation += 1;
      setBatches(rows); setError("");
    };
    const refresh = async () => {
      if (pending || !live) return;
      pending = true;
      const requestGeneration = generation;
      try {
        const [active, recent] = await Promise.all([workflowsService.imports(true), workflowsService.imports()]);
        // A newer socket snapshot must not be replaced by a slower HTTP result.
        if (live && generation === requestGeneration) {
          const ids = new Set(active.map(row => row.id));
          accept([...active, ...recent.filter(row => !ids.has(row.id)).slice(0, 20)]);
        }
      } catch { if (live && Date.now() - lastSnapshot > 6000) setError("進捗への接続を再試行中です。ジョブの停止を意味しません。"); }
      finally { pending = false; }
    };
    const connect = () => {
      if (!live) return;
      try {
        const candidate = new WebSocket(`${WS_BASE_URL}/play-imports`);
        socket = candidate;
        candidate.onmessage = event => {
          if (!live || socket !== candidate) return;
          try {
            const data = JSON.parse(event.data);
            if (data.type === "import_queue" && Array.isArray(data.batches)) {
              lastSnapshot = Date.now(); accept(data.batches);
            }
          } catch { /* HTTP fallback retains the last known queue. */ }
        };
        candidate.onerror = () => candidate.close();
        candidate.onclose = () => {
          if (socket !== candidate) return;
          socket = undefined;
          if (live) reconnect = setTimeout(connect, 3000);
        };
      } catch { reconnect = setTimeout(connect, 3000); }
    };
    connect(); void refresh();
    const timer = setInterval(() => { if (Date.now() - lastSnapshot > 6000) void refresh(); }, 3000);
    const onChange = () => { lastSnapshot = 0; void refresh(); };
    window.addEventListener("plumdeck:imports-changed", onChange);
    return () => {
      live = false; clearTimeout(reconnect); clearInterval(timer);
      window.removeEventListener("plumdeck:imports-changed", onChange);
      if (socket) {
        const candidate = socket;
        socket = undefined;
        candidate.onclose = null;
        candidate.close();
      }
    };
  }, []);
  return { batches, error };
}
