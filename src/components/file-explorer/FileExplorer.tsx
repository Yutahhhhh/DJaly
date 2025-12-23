import { useState, useEffect, useCallback, useRef } from "react";
import { EyeOff, ListMusic } from "lucide-react";
import { Checkbox } from "@/components/ui/checkbox";
import { Label } from "@/components/ui/label";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { FileItem } from "./types";
import { Breadcrumbs } from "./Breadcrumbs";
import { FileList } from "./FileList";
import { AnalysisModal } from "./AnalysisModal";
import { settingsService } from "@/services/settings";
import { filesystemService } from "@/services/filesystem";
import { ingestService } from "@/services/ingest";
import { useIngestion } from "@/contexts/IngestionContext";

export function FileExplorer() {
  const [currentPath, setCurrentPath] = useState<string>("");
  const [items, setItems] = useState<FileItem[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [selectedPaths, setSelectedPaths] = useState<Set<string>>(new Set());
  
  const { isAnalyzing, waitForIngestionComplete, startIngestion } = useIngestion();

  // Modal State (Confirm Only)
  const [isModalOpen, setIsModalOpen] = useState(false);

  // Filters
  const [hideAnalyzed, setHideAnalyzed] = useState(true);
  const [forceUpdate, setForceUpdate] = useState(false);

  // Refs
  const currentPathRef = useRef<string>(currentPath);

  useEffect(() => {
    currentPathRef.current = currentPath;
  }, [currentPath]);

  // Fetch Items
  const fetchItems = useCallback(
    async (path: string) => {
      setIsLoading(true);
      try {
        const data = await filesystemService.list(path, hideAnalyzed);
        setItems(data || []);
        setCurrentPath(path);
      } catch (error) {
        console.error("Error fetching items:", error);
        setItems([]);
      } finally {
        setIsLoading(false);
      }
    },
    [hideAnalyzed]
  );

  const fetchSettings = async () => {
    try {
      const data = await settingsService.getAll();
      if (data["root_path"]) {
        fetchItems(data["root_path"]);
      } else {
        fetchItems("/Users");
      }
    } catch (e) {
      console.error("Failed to fetch settings", e);
    }
  };

  useEffect(() => {
    fetchSettings();
  }, []);

  useEffect(() => {
    if (currentPath) {
      fetchItems(currentPath);
    }
  }, [hideAnalyzed]);

  // --- Actions ---

  const handleIngestStart = async () => {
    const targets = Array.from(selectedPaths);
    if (targets.length === 0) return;

    try {
      // Start ingestion via Context (handles state sync)
      await startIngestion(targets, forceUpdate);

      // Close local modal immediately so GlobalProgressIndicator takes over
      setIsModalOpen(false);
      
      // Wait for completion (via Context)
      await waitForIngestionComplete();

      // Analysis finished
      setSelectedPaths(new Set());
      setForceUpdate(false);
      if (currentPathRef.current) fetchItems(currentPathRef.current);
    } catch (e: any) {
      console.error("Ingest start failed", e);
      alert("Failed to start analysis: " + e.message);
    }
  };

  const handleNavigate = (path: string) => {
    fetchItems(path);
  };

  const toggleSelection = (path: string) => {
    const newSelection = new Set(selectedPaths);
    if (newSelection.has(path)) {
      newSelection.delete(path);
    } else {
      newSelection.add(path);
    }
    setSelectedPaths(newSelection);
  };

  const clearSelection = () => {
    setSelectedPaths(new Set());
    setForceUpdate(false);
  };

  return (
    <div className="h-full flex flex-col gap-4 p-4 relative">
      <div className="flex items-center justify-between">
        <h2 className="text-2xl font-bold">File Explorer</h2>
      </div>

      <div className="flex items-center justify-between gap-4">
        <Breadcrumbs currentPath={currentPath} onNavigate={handleNavigate} />

        <div className="flex items-center space-x-4 shrink-0">
          <div className="flex items-center space-x-2">
            <Checkbox
              id="hide-analyzed"
              checked={hideAnalyzed}
              onCheckedChange={(checked: boolean | string) => setHideAnalyzed(checked === true)}
            />
            <Label
              htmlFor="hide-analyzed"
              className="text-sm cursor-pointer flex items-center gap-2"
            >
              <EyeOff className="h-3 w-3" />
              Hide Analyzed
            </Label>
          </div>
        </div>
      </div>

      <Card className="flex-1 overflow-hidden flex flex-col relative">
        <FileList
          items={items}
          selectedPaths={selectedPaths}
          hideAnalyzed={hideAnalyzed}
          isLoading={isLoading}
          disabled={isAnalyzing}
          onToggleSelection={toggleSelection}
          onNavigate={handleNavigate}
        />

        {/* Floating Action Button for Selection Confirmation within Explorer */}
        {selectedPaths.size > 0 && !isAnalyzing && (
          <div className="absolute bottom-6 right-6 animate-in zoom-in duration-200">
            <Button
              size="lg"
              className="rounded-full shadow-xl h-14 px-6 gap-2 bg-primary hover:bg-primary/90 transition-all"
              onClick={() => setIsModalOpen(true)}
            >
              <ListMusic className="h-5 w-5" />
              Analyze ({selectedPaths.size})
            </Button>
          </div>
        )}
      </Card>

      <AnalysisModal
        isOpen={isModalOpen}
        onOpenChange={setIsModalOpen}
        selectedPaths={selectedPaths}
        forceUpdate={forceUpdate}
        onSetForceUpdate={setForceUpdate}
        onToggleSelection={toggleSelection}
        onClearSelection={clearSelection}
        onIngest={handleIngestStart}
      />
    </div>
  );
}
