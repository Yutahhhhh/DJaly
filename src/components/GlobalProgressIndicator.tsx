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
} from "lucide-react";
import { cn } from "@/lib/utils";
import { useIngestion } from "@/contexts/IngestionContext";

export function GlobalProgressIndicator() {
  const {
    isAnalyzing,
    progress,
    statusText,
    currentFile,
    stats,
    showComplete,
    cancelIngestion,
    dismissComplete,
  } = useIngestion();

  const [isOpen, setIsOpen] = useState(false);

  // Auto-close logic when complete
  useEffect(() => {
    if (showComplete) {
      const timer = setTimeout(() => {
        setIsOpen(false);
        dismissComplete();
      }, 5000);
      return () => clearTimeout(timer);
    }
  }, [showComplete, dismissComplete]);

  const getFileName = (path: string) => {
    if (!path) return "";
    return path.split(/[/\\]/).pop() || path;
  };

  const handleCancel = async () => {
    await cancelIngestion();
    setIsOpen(false);
  };

  // 表示すべき状態でない場合は何もレンダリングしない
  if (!isAnalyzing && !showComplete && !isOpen) {
    return null;
  }

  return (
    <>
      {/* Floating Action Button (FAB) */}
      <div className="fixed bottom-6 right-6 z-50">
        <Button
          variant="outline"
          onClick={() => setIsOpen(true)}
          className={cn(
            "h-12 rounded-full shadow-lg border pl-3 pr-5 gap-3 transition-all duration-300",
            isAnalyzing
              ? "bg-background/80 backdrop-blur-md hover:bg-background/90 border-primary/20"
              : showComplete
              ? "bg-green-500 hover:bg-green-600 text-white border-green-600"
              : "bg-background"
          )}
        >
          {isAnalyzing ? (
            <>
              <div className="relative flex items-center justify-center">
                <Loader2 className="h-5 w-5 animate-spin text-primary" />
              </div>
              <div className="flex flex-col items-start text-xs leading-none gap-0.5">
                <span className="font-semibold">Analyzing</span>
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
              {isAnalyzing ? (
                <>
                  <Activity className="h-5 w-5 text-primary animate-pulse" />
                  Analyzing Library...
                </>
              ) : showComplete ? (
                <>
                  <CheckCircle2 className="h-5 w-5 text-green-500" />
                  Analysis Complete
                </>
              ) : (
                "Analysis Status"
              )}
            </DialogTitle>
            <DialogDescription>
              {isAnalyzing
                ? "Analyzing audio features, BPM, and generating embeddings."
                : "Review the results of the analysis."}
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-6 py-4">
            {/* Progress Bar */}
            <div className="space-y-2">
              <div className="flex justify-between text-xs text-muted-foreground">
                <span>Progress</span>
                <span>
                  {stats.current} / {stats.total} Files
                </span>
              </div>
              <Progress value={progress} className="h-2" />
            </div>

            {/* Current File Info */}
            <div className="bg-muted/50 rounded-lg p-3 space-y-2 border overflow-hidden">
              <div className="flex items-start gap-3">
                <div className="h-8 w-8 bg-background rounded-full flex items-center justify-center shrink-0 border">
                  {isAnalyzing ? (
                    <Loader2 className="h-4 w-4 animate-spin text-primary" />
                  ) : (
                    <FileAudio className="h-4 w-4 text-muted-foreground" />
                  )}
                </div>
                <div className="flex-1 min-w-0 grid gap-0.5">
                  <p className="text-sm font-medium truncate" title={getFileName(currentFile)}>
                    {getFileName(currentFile) || "Waiting..."}
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
            {isAnalyzing ? (
              <Button
                variant="destructive"
                onClick={handleCancel}
                className="w-full sm:w-auto"
              >
                <StopCircle className="h-4 w-4 mr-2" />
                Stop Analysis
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
