import React, { useState } from "react";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { genreService } from "@/services/genres";
import { Loader2, AlertCircle, CheckCircle2 } from "lucide-react";
import { useIngestion } from "@/contexts/IngestionContext";

export const AnalyzeAllTab: React.FC = () => {
  const [mode, setMode] = useState<"keep" | "overwrite">("keep");
  const [localProcessing, setLocalProcessing] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  // Use global context to track status
  const { isAnalyzing, statusText, stats, showComplete } = useIngestion();

  // If global analysis is running, disable local button
  const isBusy = isAnalyzing || localProcessing;

  const handleAnalyze = async () => {
    setLocalProcessing(true);
    setErrorMessage(null);

    try {
      await genreService.startAnalyzeAll(mode);
      // Success: The global indicator will take over from here via WebSocket
    } catch (error: any) {
      console.error("Analysis failed to start", error);
      setErrorMessage(error.message || "Failed to start analysis.");
    } finally {
      setLocalProcessing(false);
    }
  };

  return (
    <div className="h-full flex flex-col space-y-6 p-4">
      <div className="space-y-4">
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

          <Button
            onClick={handleAnalyze}
            disabled={isBusy}
            className="w-full sm:w-auto"
          >
            {isBusy ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
            {isBusy ? "Analysis Running..." : "Start Analysis"}
          </Button>
        </div>

        {/* Status Feedback */}
        {errorMessage && (
          <div className="flex items-center gap-2 text-sm text-destructive bg-destructive/10 p-3 rounded-md">
            <AlertCircle className="h-4 w-4" />
            {errorMessage}
          </div>
        )}

        {isAnalyzing && (
          <div className="flex items-center gap-2 text-sm text-primary bg-primary/10 p-3 rounded-md animate-pulse">
            <Loader2 className="h-4 w-4 animate-spin" />
            <span>
              Analyzing... {stats.current} / {stats.total} ({statusText})
            </span>
          </div>
        )}

        {showComplete && !isAnalyzing && (
          <div className="flex items-center gap-2 text-sm text-green-600 bg-green-100 p-3 rounded-md">
            <CheckCircle2 className="h-4 w-4" />
            Analysis completed successfully. Check the Library or Suggestions
            tab for results.
          </div>
        )}
      </div>
    </div>
  );
};
