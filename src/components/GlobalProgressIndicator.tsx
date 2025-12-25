import { useState, useEffect } from "react";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import {
  Loader2,
  CheckCircle2,
  Activity,
  StopCircle,
  FileAudio,
  Music,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { useIngestion } from "@/contexts/IngestionContext";
import { useMetadata } from "@/contexts/MetadataContext";

export function GlobalProgressIndicator() {
  const {
    isAnalyzing: isIngesting,
    progress: ingestProgress,
    statusText: ingestStatus,
    currentFile: ingestFile,
    stats: ingestStats,
    showComplete: ingestComplete,
    cancelIngestion,
    dismissComplete: dismissIngestComplete,
  } = useIngestion();

  const {
    isUpdating: isMetadataUpdating,
    progress: metadataProgress,
    statusText: metadataStatus,
    currentTrack: metadataTrack,
    stats: metadataStats,
    cancelUpdate: cancelMetadataUpdate,
  } = useMetadata();

  const [isOpen, setIsOpen] = useState(false);

  // Determine active task
  const isWorking = isIngesting || isMetadataUpdating;
  const showComplete = ingestComplete; // Metadata doesn't have explicit complete state yet

  // Derived values based on priority (Ingestion > Metadata)
  const activeType = isIngesting ? "ingestion" : isMetadataUpdating ? "metadata" : null;
  
  const progress = isIngesting ? ingestProgress : metadataProgress;
  const statusText = isIngesting ? ingestStatus : metadataStatus;
  const currentItem = isIngesting ? ingestFile : metadataTrack;
  const stats = isIngesting ? ingestStats : metadataStats;

  // Auto-close logic when complete
  useEffect(() => {
    if (showComplete) {
      const timer = setTimeout(() => {
        setIsOpen(false);
        dismissIngestComplete();
      }, 5000);
      return () => clearTimeout(timer);
    }
  }, [showComplete, dismissIngestComplete]);

  const getFileName = (path: string) => {
    if (!path) return "";
    return path.split(/[/\\]/).pop() || path;
  };

  const handleCancel = async () => {
    if (isIngesting) {
      await cancelIngestion();
    } else if (isMetadataUpdating) {
      await cancelMetadataUpdate();
    }
    setIsOpen(false);
  };

  // 表示すべき状態でない場合は何もレンダリングしない
  if (!isWorking && !showComplete && !isOpen) {
    return null;
  }

  const title = isIngesting ? "Analyzing Library" : "Updating Metadata";
  const description = isIngesting 
    ? "Analyzing audio features, BPM, and generating embeddings."
    : "Fetching and updating track metadata.";

  return (
    <>
      {/* Floating Action Button (FAB) */}
      <div className="fixed bottom-6 right-6 z-50">
        <Button
          variant="outline"
          onClick={() => setIsOpen(true)}
          className={cn(
            "h-12 rounded-full shadow-lg border pl-3 pr-5 gap-3 transition-all duration-300",
            isWorking
              ? "bg-background/80 backdrop-blur-md hover:bg-background/90 border-primary/20"
              : showComplete
              ? "bg-green-500 hover:bg-green-600 text-white border-green-600"
              : "bg-background"
          )}
        >
          {isWorking ? (
            <>
              <div className="relative flex items-center justify-center">
                <Loader2 className="h-5 w-5 animate-spin text-primary" />
              </div>
              <div className="flex flex-col items-start text-xs leading-none gap-0.5">
                <span className="font-semibold">{activeType === "ingestion" ? "Analyzing" : "Updating"}</span>
                <span className="text-muted-foreground tabular-nums">
                  {Math.round(progress)}% • {stats.current}/{stats.total}
                </span>
              </div>
            </>
          ) : showComplete ? (
            <>
              <CheckCircle2 className="h-5 w-5" />
              <span className="font-medium">Complete</span>
            </>
          ) : (
            <Activity className="h-5 w-5" />
          )}
        </Button>
      </div>

      {/* Detail Dialog */}
      <Dialog open={isOpen} onOpenChange={setIsOpen}>
        <DialogContent className="sm:max-w-xl">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              {isWorking ? (
                <>
                  <Activity className="h-5 w-5 text-primary animate-pulse" />
                  {title}
                </>
              ) : showComplete ? (
                <>
                  <CheckCircle2 className="h-5 w-5 text-green-500" />
                  Analysis Complete
                </>
              ) : (
                "Task Status"
              )}
            </DialogTitle>
            <DialogDescription>
              {isWorking ? description : "Review the results."}
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-6 py-4">
            {/* Progress Bar */}
            <div className="space-y-2">
              <div className="flex justify-between text-xs text-muted-foreground">
                <span>Progress</span>
                <span>
                  {stats.current} / {stats.total} {activeType === "ingestion" ? "Files" : "Tracks"}
                </span>
              </div>
              <Progress value={progress} className="h-2" />
            </div>

            {/* Current File Info */}
            <div className="bg-muted/50 rounded-lg p-3 space-y-2 border overflow-hidden">
              <div className="flex items-start gap-3">
                <div className="h-8 w-8 bg-background rounded-full flex items-center justify-center shrink-0 border">
                  {isWorking ? (
                    <Loader2 className="h-4 w-4 animate-spin text-primary" />
                  ) : (
                    activeType === "ingestion" ? <FileAudio className="h-4 w-4 text-muted-foreground" /> : <Music className="h-4 w-4 text-muted-foreground" />
                  )}
                </div>
                <div className="flex-1 min-w-0 grid gap-0.5">
                  <p className="text-sm font-medium truncate" title={getFileName(currentItem)}>
                    {getFileName(currentItem) || "Waiting..."}
                  </p>
                  <p className="text-xs text-muted-foreground truncate">
                    {statusText}
                  </p>
                </div>
              </div>
            </div>

            {/* Stats Grid */}
            <div className="grid grid-cols-2 gap-4">
              <div className="p-3 border rounded-md text-center">
                <div className="text-2xl font-bold">{stats.processed}</div>
                <div className="text-xs text-muted-foreground">Processed</div>
              </div>
              <div className="p-3 border rounded-md text-center">
                <div className="text-2xl font-bold">
                  {stats.total - stats.current}
                </div>
                <div className="text-xs text-muted-foreground">Remaining</div>
              </div>
            </div>
          </div>

          <DialogFooter className="sm:justify-between gap-2">
            {isWorking ? (
              <Button
                variant="destructive"
                onClick={handleCancel}
                className="w-full sm:w-auto"
              >
                <StopCircle className="h-4 w-4 mr-2" />
                Stop {activeType === "ingestion" ? "Analysis" : "Update"}
              </Button>
            ) : (
              <Button
                onClick={() => setIsOpen(false)}
                className="w-full sm:w-auto ml-auto"
              >
                Close
              </Button>
            )}
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
