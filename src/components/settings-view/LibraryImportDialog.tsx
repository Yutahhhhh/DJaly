import { ScrollArea } from "@/components/ui/scroll-area";
import { Check } from "lucide-react";
import { LibraryAnalysisResult } from "@/services/settings";
import { AnalysisDialog } from "./AnalysisDialog";

interface LibraryImportDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  analysis: LibraryAnalysisResult | null;
  isAnalyzing: boolean;
  isImporting: boolean;
  onExecute: () => void;
}

export function LibraryImportDialog({
  open,
  onOpenChange,
  analysis,
  isAnalyzing,
  isImporting,
  onExecute,
}: LibraryImportDialogProps) {
  const canExecute = !!(analysis?.new_tracks.length || analysis?.path_updates.length);

  return (
    <AnalysisDialog
      open={open}
      onOpenChange={onOpenChange}
      title="CSV Import Analysis"
      description="Review the changes before applying. Duplicates are skipped automatically."
      isAnalyzing={isAnalyzing}
      isImporting={isImporting}
      onExecute={onExecute}
      canExecute={canExecute}
    >
      {analysis && (
        <div className="space-y-6">
          <div className="grid grid-cols-3 gap-4 text-center">
            <div className="p-3 bg-green-50 rounded-lg border border-green-100">
              <div className="text-2xl font-bold text-green-700">
                {analysis.new_tracks.length}
              </div>
              <div className="text-xs text-green-600 font-medium">
                New Tracks
              </div>
            </div>
            <div className="p-3 bg-blue-50 rounded-lg border border-blue-100">
              <div className="text-2xl font-bold text-blue-700">
                {analysis.path_updates.length}
              </div>
              <div className="text-xs text-blue-600 font-medium">
                Path Updates
              </div>
            </div>
            <div className="p-3 bg-gray-50 rounded-lg border border-gray-100 opacity-70">
              <div className="text-2xl font-bold text-gray-700">
                {analysis.duplicates.length}
              </div>
              <div className="text-xs text-gray-600 font-medium">
                Skipped (Duplicates)
              </div>
            </div>
          </div>

          {analysis.path_updates.length > 0 && (
            <div className="space-y-2">
              <h4 className="text-sm font-medium">Path Update Preview</h4>
              <ScrollArea className="h-[150px] border rounded-md p-2 bg-muted/30">
                <div className="space-y-2 text-xs">
                  {analysis.path_updates.map((update, idx) => (
                    <div
                      key={idx}
                      className="flex flex-col gap-1 p-2 bg-background rounded border"
                    >
                      <div className="font-semibold">
                        {update.track.title}
                      </div>
                      <div className="text-red-500 line-through truncate opacity-70">
                        {update.old_path}
                      </div>
                      <div className="text-green-600 truncate flex items-center gap-1">
                        <Check className="h-3 w-3" />
                        {update.new_path}
                      </div>
                    </div>
                  ))}
                </div>
              </ScrollArea>
            </div>
          )}
        </div>
      )}
    </AnalysisDialog>
  );
}
