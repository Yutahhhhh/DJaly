import { createContext, useContext, useEffect, useState, useCallback, useRef, ReactNode } from "react";
import { ingestionSocket, IngestMessage, IngestTerminalType } from "@/services/ingestion-socket";
import { ingestService } from "@/services/ingest";
import { apiClient } from "@/services/api-client";
import { normalizeAnalysisProfile, type AnalysisProfile } from "@/services/analysis-profile";

interface IngestionStats {
  current: number;
  total: number;
  processed: number;
  skipped: number;
  errors: number;
}

export interface IngestionOutcome extends IngestionStats {
  type: IngestTerminalType;
  message: string;
  lastError: string;
  failedFiles: string[];
}

interface IngestionContextType {
  isAnalyzing: boolean;
  progress: number;
  statusText: string;
  currentFile: string;
  stats: IngestionStats;
  showComplete: boolean;
  lastError: string;
  elapsedSeconds: number;
  activeFiles: Array<{ path: string; seconds: number; stage: string }>;
  connectionError: string;
  analysisProfile: AnalysisProfile;
  effectiveAnalysisProfile: "light" | "full";
  /** Waiting for a Play import or another analysis to release the shared slot. */
  queued: boolean;
  cancelIngestion: () => Promise<void>;
  dismissComplete: () => void;
  waitForIngestionComplete: () => Promise<IngestionOutcome>;
  startIngestion: (targets: string[], forceUpdate: boolean, analysisProfile?: AnalysisProfile) => Promise<void>;
}

const IngestionContext = createContext<IngestionContextType | undefined>(undefined);
const terminal = new Set<IngestMessage["type"]>(["complete", "cancelled", "error", "idle"]);

function statsOf(snapshot: IngestMessage): IngestionStats {
  const processed = Number(snapshot.processed ?? 0);
  const skipped = Number(snapshot.skipped ?? 0);
  const errors = Number(snapshot.errors ?? 0);
  return {
    total: Number(snapshot.total ?? 0),
    processed,
    skipped,
    errors,
    current: processed + skipped + errors,
  };
}

function outcomeOf(snapshot: IngestMessage): IngestionOutcome {
  const type = terminal.has(snapshot.type) ? snapshot.type as IngestTerminalType : "idle";
  const lastError = String(
    snapshot.details?.last_error ||
    (snapshot.type === "error" ? snapshot.message || "解析に失敗しました" : ""),
  );
  const failedFiles = Array.isArray(snapshot.details?.failed_files)
    ? snapshot.details.failed_files.filter((path: unknown): path is string => typeof path === "string")
    : [];
  return { type, ...statsOf(snapshot), message: String(snapshot.message || ""), lastError, failedFiles };
}

export function IngestionProvider({ children }: { children: ReactNode }) {
  const initial: IngestMessage = { type: "idle" };
  const [snapshot, setSnapshot] = useState<IngestMessage>(initial);
  const [showComplete, setShowComplete] = useState(false);
  const [connectionError, setConnectionError] = useState("");
  const [now, setNow] = useState(Date.now());
  const snapshotRef = useRef<IngestMessage>(initial);
  const isAnalyzingRef = useRef(false);
  const clientGeneration = useRef(0);
  const lastMessage = useRef(0);
  const lastSignature = useRef("");
  const completionResolvers = useRef<Array<(outcome: IngestionOutcome) => void>>([]);
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);

  const accept = useCallback((data: IngestMessage) => {
    const current = snapshotRef.current;
    const currentActive = !terminal.has(current.type);
    const sameRun = Boolean(data.run_id && current.run_id && data.run_id === current.run_id);
    if (sameRun && Number(data.revision ?? 0) < Number(current.revision ?? 0)) return;
    // A previous socket/status request must not terminate a newly started run.
    if (currentActive && current.run_id && data.run_id !== current.run_id) return;

    const signature = JSON.stringify(data);
    setConnectionError("");
    if (signature === lastSignature.current) return;
    lastSignature.current = signature;
    clientGeneration.current += 1;
    snapshotRef.current = data;
    setSnapshot(data);

    const wasRunning = isAnalyzingRef.current;
    const running = !terminal.has(data.type);
    isAnalyzingRef.current = running;
    if (running) {
      setShowComplete(false);
      clearTimeout(timer.current);
      return;
    }

    const outcome = outcomeOf(data);
    completionResolvers.current.splice(0).forEach(resolve => resolve(outcome));
    if (data.type === "error" || data.type === "complete" && (wasRunning || outcome.errors > 0) || data.type === "cancelled" && wasRunning) {
      setShowComplete(true);
      clearTimeout(timer.current);
      if (data.type === "complete" && outcome.errors === 0 || data.type === "cancelled") {
        timer.current = setTimeout(() => setShowComplete(false), 5000);
      }
    }
  }, []);

  useEffect(() => {
    let live = true;
    let pending = false;
    const unsubscribe = ingestionSocket.addMessageListener(data => {
      if (!live) return;
      lastMessage.current = Date.now();
      accept(data);
    });
    const restore = async () => {
      if (pending || !live) return;
      pending = true;
      const generation = clientGeneration.current;
      try {
        const state = await apiClient.get<IngestMessage>("/ingest/status", undefined, 5000);
        if (live && clientGeneration.current === generation) accept(state);
      } catch {
        if (live && Date.now() - lastMessage.current > 6000) {
          setConnectionError("進捗への接続を再試行中です。解析処理は継続しています");
        }
      } finally {
        pending = false;
      }
    };
    void restore();
    const poll = setInterval(() => {
      setNow(Date.now());
      if (Date.now() - lastMessage.current > 6000) void restore();
    }, 3000);
    return () => {
      live = false;
      unsubscribe();
      clearInterval(poll);
      clearTimeout(timer.current);
    };
  }, [accept]);

  const stats = statsOf(snapshot);
  const isAnalyzing = !terminal.has(snapshot.type);
  const outcome = outcomeOf(snapshot);
  const activeFiles = Object.entries(snapshot.details?.active_files ?? {}).map(([path, start]) => ({
    path,
    seconds: Math.max(0, Math.floor(now / 1000 - Number(start))),
    stage: String((snapshot.details?.active_progress as Record<string, string> | undefined)?.[path] || "解析を準備しています"),
  }));
  const statusText = snapshot.type === "complete"
    ? `解析終了：成功 ${stats.processed}・スキップ ${stats.skipped}・失敗 ${stats.errors}`
    : snapshot.type === "error" ? "解析を継続できませんでした"
    : snapshot.type === "cancelled" ? "解析をキャンセルしました"
    : snapshot.type === "idle" ? "停止中"
    : String(snapshot.details?.stage || "解析を準備中");
  const analysisProfile = normalizeAnalysisProfile(snapshot.details?.analysis_profile);
  const queued = isAnalyzing && snapshot.details?.queued === true;
  const effectiveAnalysisProfile = snapshot.details?.effective_analysis_profile === "light"
    ? "light"
    : "full";

  const dismissComplete = useCallback(() => {
    setShowComplete(false);
    clearTimeout(timer.current);
  }, []);

  const cancelIngestion = async () => {
    try {
      const result = await ingestService.cancel();
      if (result.state) accept(result.state);
    } catch (cause) {
      setConnectionError(String(cause));
      throw cause;
    }
  };

  const startIngestion = async (targets: string[], forceUpdate: boolean, requestedProfile?: AnalysisProfile) => {
    const result = await ingestService.ingest(targets, forceUpdate, requestedProfile);
    if (result.status === "error") throw new Error(result.message || "解析を開始できませんでした");
    if (!result.state) throw new Error("解析の進捗情報を取得できませんでした");
    accept(result.state);
  };

  const waitForIngestionComplete = () => new Promise<IngestionOutcome>(resolve => {
    if (!isAnalyzingRef.current) resolve(outcomeOf(snapshotRef.current));
    else completionResolvers.current.push(resolve);
  });

  return <IngestionContext.Provider value={{
    isAnalyzing,
    stats,
    progress: stats.total ? Math.min(100, stats.current / stats.total * 100) : 0,
    statusText,
    currentFile: String(snapshot.file || ""),
    showComplete,
    lastError: outcome.lastError,
    activeFiles,
    connectionError,
    analysisProfile,
    effectiveAnalysisProfile,
    queued,
    elapsedSeconds: snapshot.start_time ? Math.max(0, Math.floor(now / 1000 - Number(snapshot.start_time))) : 0,
    cancelIngestion,
    dismissComplete,
    startIngestion,
    waitForIngestionComplete,
  }}>{children}</IngestionContext.Provider>;
}

export function useIngestion() {
  const context = useContext(IngestionContext);
  if (!context) throw new Error("useIngestion must be used within an IngestionProvider");
  return context;
}
