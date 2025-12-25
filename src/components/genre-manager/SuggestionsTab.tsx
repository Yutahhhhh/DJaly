import React, { useEffect, useState, useRef } from "react";
import {
  genreService,
  GenreAnalysisResult,
  GenreUpdateResult,
  AnalysisMode,
} from "@/services/genres";
import { tracksService } from "@/services/tracks";
import { Track } from "@/types";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  Loader2,
  Play,
  Wand2,
  StopCircle,
} from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Progress } from "@/components/ui/progress";

interface SuggestionsTabProps {
  onPlay: (track: Track) => void;
  mode?: AnalysisMode;
}

export const SuggestionsTab: React.FC<SuggestionsTabProps> = ({ onPlay, mode = "both" }) => {
  const [tracks, setTracks] = useState<Track[]>([]);
  const [loading, setLoading] = useState(false);

  // Batch Analysis State
  const [isBatchAnalyzing, setIsBatchAnalyzing] = useState(false);
  const [isPreparing, setIsPreparing] = useState(false);
  // const [analysisMode, setAnalysisMode] = useState<AnalysisMode>("both"); // Removed
  const [batchProgress, setBatchProgress] = useState(0);
  const [batchTotal, setBatchTotal] = useState(0);
  const [processedCount, setProcessedCount] = useState(0);
  const abortRef = useRef(false);

  // Single Analysis State
  const [analyzingId, setAnalyzingId] = useState<number | null>(null);
  const [analysisResult, setAnalysisResult] =
    useState<GenreAnalysisResult | null>(null);
  const [isDialogOpen, setIsDialogOpen] = useState(false);
  const [editedGenre, setEditedGenre] = useState("");
  const [currentTrack, setCurrentTrack] = useState<Track | null>(null);

  const fetchTracks = async () => {
    setLoading(true);
    try {
      const data = await genreService.getUnknownTracks(0, 50, mode);
      setTracks(data);
    } catch (error) {
      console.error("Failed to fetch tracks", error);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchTracks();
  }, [mode]);

  const handleAnalyze = async (track: Track) => {
    setAnalyzingId(track.id);
    setCurrentTrack(track);
    try {
      const result = await genreService.analyzeTrackWithLlm(track.id, false, mode);
      setAnalysisResult(result);
      setEditedGenre(mode === "subgenre" ? (result.subgenre || "") : result.genre);
      setIsDialogOpen(true);
    } catch (error: any) {
      console.error("Failed to analyze", error);
      alert(`Analysis Failed: ${error.message || "Unknown Error"}`);
    } finally {
      setAnalyzingId(null);
    }
  };

  const handleConfirmSingle = async () => {
    if (!currentTrack) return;
    try {
      await tracksService.updateGenre(currentTrack.id, editedGenre);
      setTracks((prev) => prev.filter((t) => t.id !== currentTrack.id));
      setIsDialogOpen(false);
      setAnalysisResult(null);
      setCurrentTrack(null);
    } catch (error) {
      console.error("Failed to update genre", error);
    }
  };

  const downloadCsv = (results: GenreUpdateResult[]) => {
    if (results.length === 0) return;
    
    const headers = ["Track ID", "Title", "Artist", "Old Genre", "New Genre"];
    const rows = results.map(r => [
      r.track_id,
      `"${r.title.replace(/"/g, '""')}"`,
      `"${r.artist.replace(/"/g, '""')}"`,
      `"${r.old_genre}"`,
      `"${r.new_genre}"`
    ]);
    
    const csvContent = [
      headers.join(","),
      ...rows.map(r => r.join(","))
    ].join("\n");
    
    const blob = new Blob([csvContent], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.setAttribute("href", url);
    link.setAttribute("download", `genre_analysis_results_${new Date().toISOString().slice(0,19).replace(/[:T]/g,"-")}.csv`);
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  };

  const handleBatchAnalyze = async (targetMode: AnalysisMode) => {
    if (tracks.length === 0) return;
    if (isPreparing) return;
    
    setIsPreparing(true);
    
    // First, get ALL unknown IDs to know the scope
    let allIds: number[] = [];
    try {
      // If targetMode is "both", we want all unverified tracks regardless of current view mode
      // If targetMode is specific, we use the current view mode logic (which filters by subgenre emptiness if mode=subgenre)
      allIds = await genreService.getAllUnknownTrackIds(targetMode === "both" ? "genre" : mode);
    } catch (e) {
      console.error("Failed to get all IDs", e);
      alert("Failed to start: Could not fetch track list.");
      setIsPreparing(false);
      return;
    }

    if (allIds.length === 0) {
      alert("No unknown tracks found.");
      setIsPreparing(false);
      return;
    }

    setIsBatchAnalyzing(true);
    setIsPreparing(false);
    abortRef.current = false;
    setBatchTotal(allIds.length);
    setProcessedCount(0);
    setBatchProgress(0);
    
    const allResults: GenreUpdateResult[] = [];
    const BATCH_SIZE = 50;
    const CONCURRENCY = 3; // Run 3 batches in parallel

    // Create chunks
    const chunks: number[][] = [];
    for (let i = 0; i < allIds.length; i += BATCH_SIZE) {
        chunks.push(allIds.slice(i, i + BATCH_SIZE));
    }

    let completedCount = 0;

    const processChunk = async (chunkIds: number[]) => {
        if (abortRef.current) return;
        try {
            const results = await genreService.analyzeTracksBatchWithLlm(chunkIds, targetMode);
            allResults.push(...results);
        } catch (error: any) {
            console.error("Chunk failed", error);
        } finally {
            completedCount += chunkIds.length;
            setProcessedCount(Math.min(completedCount, allIds.length));
            setBatchProgress(Math.min((completedCount / allIds.length) * 100, 100));
        }
    };

    try {
      const executing = new Set<Promise<void>>();
      
      for (const chunk of chunks) {
        if (abortRef.current) break;
        
        const p = processChunk(chunk).then(() => {
            executing.delete(p);
        });
        executing.add(p);
        
        if (executing.size >= CONCURRENCY) {
            await Promise.race(executing);
        }
        
        // Small delay to prevent UI freeze
        await new Promise(resolve => setTimeout(resolve, 50));
      }
      
      await Promise.all(executing);

    } catch (error: any) {
      console.error("Batch analysis failed", error);
      alert(`Batch analysis stopped: ${error.message}`);
    } finally {
      setIsBatchAnalyzing(false);
      fetchTracks(); // Refresh view
      
      // 完了通知はUI更新のみとし、ダイアログは出さない
      if (allResults.length > 0) {
        // CSVダウンロードも自動では行わない（ダイアログ削減のため）
        downloadCsv(allResults);
      }
    }
  };

  const handleStopBatch = () => {
    abortRef.current = true;
  };

  return (
    <div className="h-full flex flex-col gap-4">
      <div className="flex items-center justify-between px-4 pt-4">
        <div>
          <h3 className="text-lg font-semibold">Unknown Genre Tracks</h3>
          <p className="text-sm text-muted-foreground">
            Showing first 50 of {loading ? "..." : "many"} unknown tracks.
          </p>
        </div>
        <div className="flex gap-2">
          {isBatchAnalyzing ? (
            <Button variant="destructive" onClick={handleStopBatch}>
              <StopCircle className="mr-2 h-4 w-4" />
              Stop Analysis
            </Button>
          ) : (
            <>
              <Button
                variant="outline"
                onClick={fetchTracks}
                disabled={loading}
              >
                Refresh
              </Button>

              <div className="flex gap-2">
                <Button
                  onClick={() => handleBatchAnalyze(mode)}
                  disabled={loading || tracks.length === 0 || isPreparing}
                  variant="secondary"
                >
                  {isPreparing ? (
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  ) : (
                    <Wand2 className="mr-2 h-4 w-4" />
                  )}
                  Analyze {mode === "subgenre" ? "Subgenres" : "Genres"}
                </Button>

                <Button
                  onClick={() => handleBatchAnalyze("both")}
                  disabled={loading || tracks.length === 0 || isPreparing}
                >
                  {isPreparing ? (
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  ) : (
                    <Wand2 className="mr-2 h-4 w-4" />
                  )}
                  Analyze All
                </Button>
              </div>
            </>
          )}
        </div>
      </div>

      {isBatchAnalyzing && (
        <div className="bg-muted p-4 rounded-md space-y-2">
          <div className="flex justify-between text-sm">
            <span>
              Processing... {processedCount} / {batchTotal}
            </span>
            <span>{Math.round(batchProgress)}%</span>
          </div>
          <Progress value={batchProgress} className="h-2" />
          <p className="text-xs text-muted-foreground">
            Analyzing in batches of 50. Changes are auto-applied.
          </p>
        </div>
      )}

      <ScrollArea className="flex-1 border-t">
        <div className="p-4 space-y-2">
          {loading ? (
            <div className="flex justify-center p-8">
              <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
            </div>
          ) : tracks.length === 0 ? (
            <div className="text-center p-8 text-muted-foreground">
              No unknown tracks found. Good job!
            </div>
          ) : (
            tracks.map((track) => (
              <div
                key={track.id}
                className="flex items-center justify-between p-3 border rounded-md hover:bg-accent/50 transition-colors"
              >
                <div className="flex items-center gap-3 overflow-hidden">
                  <Button
                    size="icon"
                    variant="ghost"
                    className="h-8 w-8 shrink-0"
                    onClick={() => onPlay(track)}
                  >
                    <Play className="h-4 w-4" />
                  </Button>
                  <div className="min-w-0">
                    <div className="font-medium truncate">{track.title}</div>
                    <div className="text-sm text-muted-foreground truncate">
                      {track.artist}
                    </div>
                  </div>
                </div>

                <div className="flex items-center gap-2 shrink-0">
                  <Button
                    size="sm"
                    variant="secondary"
                    onClick={() => handleAnalyze(track)}
                    disabled={analyzingId === track.id || isBatchAnalyzing}
                  >
                    {analyzingId === track.id ? (
                      <Loader2 className="h-3 w-3 animate-spin" />
                    ) : (
                      "Analyze Single"
                    )}
                  </Button>
                </div>
              </div>
            ))
          )}
        </div>
      </ScrollArea>

      <Dialog open={isDialogOpen} onOpenChange={setIsDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Genre Analysis Result</DialogTitle>
            <DialogDescription>
              AI suggested a genre for "{currentTrack?.title}".
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-4 py-4">
            <div className="space-y-2">
              <Label>Suggested Genre</Label>
              <Input
                value={editedGenre}
                onChange={(e) => setEditedGenre(e.target.value)}
              />
            </div>
            {analysisResult && (
              <div className="text-sm space-y-1 bg-muted p-3 rounded-md">
                <div className="flex justify-between">
                  <span className="font-medium">Reason:</span>
                  <span className="text-muted-foreground">
                    {analysisResult.confidence} Confidence
                  </span>
                </div>
                <p>{analysisResult.reason}</p>
              </div>
            )}
          </div>

          <DialogFooter>
            <Button variant="outline" onClick={() => setIsDialogOpen(false)}>
              Cancel
            </Button>
            <Button onClick={handleConfirmSingle}>Apply Genre</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
};
