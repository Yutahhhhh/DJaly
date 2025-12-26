import {
  createContext,
  useContext,
  useEffect,
  useState,
  useCallback,
  ReactNode,
} from "react";
import { metadataSocket, MetadataMessage } from "@/services/metadata-socket";
import { metadataService } from "@/services/metadata";

interface MetadataStats {
  total: number;
  current: number;
  processed: number;
  updated: number;
  skipped: number;
  errors: number;
}

interface MetadataContextType {
  isUpdating: boolean;
  progress: number;
  statusText: string;
  currentTrack: string;
  stats: MetadataStats;
  startUpdate: (type: "release_date" | "lyrics", overwrite: boolean, trackIds?: number[]) => Promise<void>;
  cancelUpdate: () => Promise<void>;
  clearSkipCache: (type?: "release_date" | "lyrics") => Promise<void>;
}

const MetadataContext = createContext<MetadataContextType | undefined>(undefined);

export function MetadataProvider({ children }: { children: ReactNode }) {
  const [isUpdating, setIsUpdating] = useState(false);
  const [progress, setProgress] = useState(0);
  const [statusText, setStatusText] = useState("");
  const [currentTrack, setCurrentTrack] = useState("");
  const [stats, setStats] = useState<MetadataStats>({
    total: 0,
    current: 0,
    processed: 0,
    updated: 0,
    skipped: 0,
    errors: 0,
  });

  const handleSocketMessage = useCallback((data: MetadataMessage) => {
    if (data.type === "idle" || data.type === "complete" || data.type === "error") {
      setIsUpdating(false);
      if (data.type === "complete") setStatusText("Update complete!");
      if (data.type === "error") setStatusText(`Error: ${data.message}`);
    } else {
      setIsUpdating(true);
      setStatusText(data.message || "Updating...");
    }

    if (data.total !== undefined) {
      setStats({
        total: data.total || 0,
        current: data.current || 0,
        processed: data.processed || 0,
        updated: data.updated || 0,
        skipped: data.skipped || 0,
        errors: data.errors || 0,
      });
      
      if (data.total > 0 && data.current) {
        setProgress((data.current / data.total) * 100);
      }
    }

    if (data.current_track) setCurrentTrack(data.current_track);
  }, []);

  useEffect(() => {
    const unsubscribe = metadataSocket.addMessageListener(handleSocketMessage);
    return unsubscribe;
  }, [handleSocketMessage]);

  const startUpdate = async (type: "release_date" | "lyrics", overwrite: boolean, trackIds?: number[]) => {
    try {
      await metadataService.startUpdate(type, overwrite, trackIds);
    } catch (error) {
      console.error("Failed to start update", error);
    }
  };

  const cancelUpdate = async () => {
    try {
      await metadataService.cancelUpdate();
    } catch (error) {
      console.error("Failed to cancel update", error);
    }
  };

  const clearSkipCache = async (type?: "release_date" | "lyrics") => {
    try {
      await metadataService.clearSkipCache(type);
    } catch (error) {
      console.error("Failed to clear cache", error);
    }
  };

  return (
    <MetadataContext.Provider
      value={{
        isUpdating,
        progress,
        statusText,
        currentTrack,
        stats,
        startUpdate,
        cancelUpdate,
        clearSkipCache,
      }}
    >
      {children}
    </MetadataContext.Provider>
  );
}

export function useMetadata() {
  const context = useContext(MetadataContext);
  if (context === undefined) {
    throw new Error("useMetadata must be used within a MetadataProvider");
  }
  return context;
}
