import React, { useState } from "react";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { ScrollArea } from "@/components/ui/scroll-area";
import { genreService } from "@/services/genres";
import {
  Loader2,
  AlertCircle,
  CheckCircle2,
  ArrowRight,
  XCircle,
  RotateCcw,
} from "lucide-react";
import { useGenreAnalysis } from "./useGenreAnalysis";
import { getErrorDetail } from "@/services/api-client";
import { toast } from "@/components/ui/toast";

export const AnalyzeAllTab: React.FC = () => {
  const [mode, setMode] = useState<"keep" | "overwrite">("keep");
  const [localProcessing, setLocalProcessing] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  // ジャンル解析専用 WebSocket (/ws/genres/analysis) を購読
  const { state, isRunning } = useGenreAnalysis();

  const isBusy = isRunning || localProcessing;

  const handleAnalyze = async () => {
    setLocalProcessing(true);
    setErrorMessage(null);

    try {
      const res = await genreService.startAnalyzeAll(mode);
      if (res.status === "noop") {
        toast.info("解析対象の曲がありません", res.message);
      }
    } catch (error: any) {
      console.error("Analysis failed to start", error);
      setErrorMessage(getErrorDetail(error) || "Failed to start analysis.");
    } finally {
      setLocalProcessing(false);
    }
  };

  const handleCancel = async () => {
    try {
      await genreService.cancelAnalyzeAll();
    } catch (error) {
      console.error("Cancel failed", error);
    }
  };

  const handleRetryFailed = async () => {
    if (state.failed_track_ids.length === 0) return;
    try {
      await genreService.startBatchAnalysis(
        state.failed_track_ids,
        mode === "overwrite",
        "both"
      );
    } catch (error) {
      toast.error("再試行の開始に失敗しました", getErrorDetail(error));
    }
  };

  return (
    <div className="h-full flex flex-col space-y-6 p-4 overflow-hidden">
      <div className="space-y-4 shrink-0">
        <div>
          <h2 className="text-lg font-semibold">Full Library Analysis</h2>
          <p className="text-sm text-muted-foreground">
            Use LLM to analyze tracks and assign genres based on metadata and
            folder structure. This process runs in the background.
          </p>
        </div>

        <div className="space-y-4 border p-4 rounded-md bg-muted/20">
          <div className="space-y-2">
            <div className="flex items-center space-x-2">
              <input
                type="radio"
                id="keep"
                name="mode"
                value="keep"
                checked={mode === "keep"}
                onChange={() => setMode("keep")}
                className="h-4 w-4 border-gray-300 text-primary focus:ring-primary"
                disabled={isBusy}
              />
              <Label htmlFor="keep" className={isBusy ? "opacity-50" : ""}>
                Keep Confirmed (Skip verified tracks)
              </Label>
            </div>
            <div className="flex items-center space-x-2">
              <input
                type="radio"
                id="overwrite"
                name="mode"
                value="overwrite"
                checked={mode === "overwrite"}
                onChange={() => setMode("overwrite")}
                className="h-4 w-4 border-gray-300 text-primary focus:ring-primary"
                disabled={isBusy}
              />
              <Label htmlFor="overwrite" className={isBusy ? "opacity-50" : ""}>
                Overwrite All (Re-analyze everything)
              </Label>
            </div>
          </div>

          <div className="flex gap-2">
            <Button
              onClick={handleAnalyze}
              disabled={isBusy}
              className="w-full sm:w-auto"
            >
              {isBusy ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
              {isBusy ? "Analysis Running..." : "Start Analysis"}
            </Button>
            {isRunning && (
              <Button variant="outline" onClick={handleCancel}>
                <XCircle className="mr-2 h-4 w-4" /> Cancel
              </Button>
            )}
          </div>
        </div>

        {/* Status Feedback */}
        {errorMessage && (
          <div className="flex items-center gap-2 text-sm text-destructive bg-destructive/10 p-3 rounded-md">
            <AlertCircle className="h-4 w-4" />
            {errorMessage}
          </div>
        )}

        {isRunning && (
          <div className="text-sm text-primary bg-primary/10 p-3 rounded-md space-y-1">
            <div className="flex items-center gap-2">
              <Loader2 className="h-4 w-4 animate-spin" />
              <span>
                Analyzing... {state.current} / {state.total}
              </span>
            </div>
            {state.current_track && (
              <div className="text-xs text-muted-foreground pl-6 truncate">
                {state.current_track}
              </div>
            )}
            <div className="text-xs text-muted-foreground pl-6">
              更新 {state.updated} / 失敗 {state.errors}
            </div>
          </div>
        )}

        {state.type === "complete" && !isRunning && (
          <div className="flex items-center justify-between text-sm text-green-600 bg-green-100 dark:bg-green-950/40 p-3 rounded-md">
            <span className="flex items-center gap-2">
              <CheckCircle2 className="h-4 w-4" />
              完了: {state.updated} 件更新 / {state.errors} 件失敗
            </span>
            {state.failed_track_ids.length > 0 && (
              <Button size="sm" variant="outline" onClick={handleRetryFailed}>
                <RotateCcw className="mr-1.5 h-3 w-3" />
                失敗 {state.failed_track_ids.length} 件を再試行
              </Button>
            )}
          </div>
        )}
      </div>

      {/* 変更ログ (ライブ表示) */}
      {state.recent_results.length > 0 && (
        <div className="flex-1 min-h-0 flex flex-col border rounded-md">
          <div className="px-3 py-2 border-b bg-muted/30 text-xs font-semibold text-muted-foreground shrink-0">
            Changes ({state.recent_results.length} recent)
          </div>
          <ScrollArea className="flex-1">
            <div className="p-2 space-y-1">
              {[...state.recent_results].reverse().map((r, i) => (
                <div
                  key={`${r.track_id}-${i}`}
                  className="text-xs flex items-center gap-2 px-2 py-1.5 rounded bg-muted/20"
                >
                  <span className="font-medium truncate max-w-[40%]">
                    {r.artist} - {r.title}
                  </span>
                  <span className="text-muted-foreground truncate">
                    {r.old_genre}
                  </span>
                  <ArrowRight className="h-3 w-3 shrink-0 text-muted-foreground" />
                  <span className="text-primary font-medium truncate">
                    {r.new_genre}
                  </span>
                </div>
              ))}
            </div>
          </ScrollArea>
        </div>
      )}
    </div>
  );
};
