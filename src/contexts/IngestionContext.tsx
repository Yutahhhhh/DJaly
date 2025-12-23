import {
  createContext,
  useContext,
  useEffect,
  useState,
  useCallback,
  useRef,
  ReactNode,
} from "react";
import { ingestionSocket, IngestMessage } from "@/services/ingestion-socket";
import { ingestService } from "@/services/ingest";

interface IngestionStats {
  current: number;
  total: number;
  processed: number;
}

interface IngestionContextType {
  isAnalyzing: boolean;
  progress: number;
  statusText: string;
  currentFile: string;
  stats: IngestionStats;
  showComplete: boolean;
  cancelIngestion: () => Promise<void>;
  dismissComplete: () => void;
  waitForIngestionComplete: () => Promise<void>;
  startIngestion: (targets: string[], forceUpdate: boolean) => Promise<void>;
}

const IngestionContext = createContext<IngestionContextType | undefined>(
  undefined
);

export function IngestionProvider({ children }: { children: ReactNode }) {
  const [isAnalyzing, setIsAnalyzing] = useState(false);
  const isAnalyzingRef = useRef(false);
  const [progress, setProgress] = useState(0);
  const [statusText, setStatusText] = useState("");
  const [currentFile, setCurrentFile] = useState("");
  const [stats, setStats] = useState<IngestionStats>({
    current: 0,
    total: 0,
    processed: 0,
  });
  const [showComplete, setShowComplete] = useState(false);
  const completeTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const completionResolvers = useRef<(() => void)[]>([]);

  // Sync Ref with State
  useEffect(() => {
    isAnalyzingRef.current = isAnalyzing;
  }, [isAnalyzing]);

  const handleSocketMessage = useCallback((data: IngestMessage) => {
    switch (data.type) {
      case "start":
        setIsAnalyzing(true);
        // Ref will be updated by useEffect, but for safety in this callback if needed:
        isAnalyzingRef.current = true;
        setShowComplete(false);
        setStats({
          current: 0,
          total: data.total || 0,
          processed: 0,
        });
        setProgress(0);
        setStatusText("Initializing analysis...");
        break;

      case "processing":
        setIsAnalyzing(true);
        if (data.total) setStats((prev) => ({ ...prev, total: data.total! }));
        if (data.current) {
          setStats((prev) => ({ ...prev, current: data.current! }));
          const percent = ((data.current - 1) / (data.total || 1)) * 100;
          setProgress(percent);
        }
        if (data.file) setCurrentFile(data.file);
        setStatusText("Analyzing audio features...");
        break;

      case "progress":
        setIsAnalyzing(true);
        if (data.total) setStats((prev) => ({ ...prev, total: data.total! }));
        if (data.current) {
          setStats((prev) => ({ ...prev, current: data.current! }));
          const percent = (data.current / (data.total || 1)) * 100;
          setProgress(percent);
        }
        if (data.file) setCurrentFile(data.file);

        const bpmInfo = data.bpm ? `BPM: ${data.bpm.toFixed(1)}` : "";
        const keyInfo = data.key ? `Key: ${data.key}` : "";
        const extra = [bpmInfo, keyInfo].filter(Boolean).join(" | ");

        setStatusText(extra ? `Processed: ${extra}` : "Processing...");
        break;

      case "complete":
        setIsAnalyzing(false);
        setProgress(100);
        setStatusText("All files processed successfully.");
        setShowComplete(true);
        setStats((prev) => ({
          ...prev,
          processed: data.processed || prev.processed,
        }));

        if (completeTimerRef.current) clearTimeout(completeTimerRef.current);
        completeTimerRef.current = setTimeout(() => {
          setShowComplete(false);
        }, 5000);

        // Resolve waiting promises
        completionResolvers.current.forEach((resolve) => resolve());
        completionResolvers.current = [];
        break;

      case "cancelled":
        setIsAnalyzing(false);
        setStatusText("Analysis cancelled.");
        setShowComplete(false);
        // Resolve waiting promises even on cancel? Or reject?
        // For now, resolve so awaiters can proceed (maybe check status if needed)
        completionResolvers.current.forEach((resolve) => resolve());
        completionResolvers.current = [];
        break;

      case "error":
        setIsAnalyzing(false);
        setStatusText(`Error: ${data.message}`);
        // Resolve on error too to unblock UI
        completionResolvers.current.forEach((resolve) => resolve());
        completionResolvers.current = [];
        break;
    }
  }, []);

  useEffect(() => {
    const unsubscribe = ingestionSocket.addMessageListener(handleSocketMessage);
    return () => {
      unsubscribe();
      if (completeTimerRef.current) clearTimeout(completeTimerRef.current);
    };
  }, [handleSocketMessage]);

  const cancelIngestion = async () => {
    try {
      await ingestService.cancel();
    } catch (e) {
      console.error(e);
    }
  };

  const dismissComplete = () => {
    setShowComplete(false);
    if (completeTimerRef.current) clearTimeout(completeTimerRef.current);
  };

  const startIngestion = async (targets: string[], forceUpdate: boolean) => {
    isAnalyzingRef.current = true;
    setIsAnalyzing(true);
    setStatusText("Initializing ingestion...");
    try {
      await ingestService.ingest(targets, forceUpdate);
    } catch (e) {
      isAnalyzingRef.current = false;
      setIsAnalyzing(false);
      setStatusText("Failed to start ingestion");
      throw e;
    }
  };

  const waitForIngestionComplete = () => {
    return new Promise<void>((resolve) => {
      if (!isAnalyzingRef.current) {
        resolve();
        return;
      }
      completionResolvers.current.push(resolve);
    });
  };

  return (
    <IngestionContext.Provider
      value={{
        isAnalyzing,
        progress,
        statusText,
        currentFile,
        stats,
        showComplete,
        cancelIngestion,
        dismissComplete,
        waitForIngestionComplete,
        startIngestion,
      }}
    >
      {children}
    </IngestionContext.Provider>
  );
}

export function useIngestion() {
  const context = useContext(IngestionContext);
  if (context === undefined) {
    throw new Error("useIngestion must be used within an IngestionProvider");
  }
  return context;
}
