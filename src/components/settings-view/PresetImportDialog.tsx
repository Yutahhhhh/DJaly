import { ScrollArea } from "@/components/ui/scroll-area";
import { PresetAnalysisResult } from "@/services/settings";
import { AnalysisDialog } from "./AnalysisDialog";

interface PresetImportDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  analysis: PresetAnalysisResult | null;
  isAnalyzing: boolean;
  isImporting: boolean;
  onExecute: () => void;
}

export function PresetImportDialog({
  open,
  onOpenChange,
  analysis,
  isAnalyzing,
  isImporting,
  onExecute,
}: PresetImportDialogProps) {
  const canExecute = !!(analysis?.new_presets.length || analysis?.updates.length);

  return (
    <AnalysisDialog
      open={open}
      onOpenChange={onOpenChange}
      title="Preset Import Analysis"
      description="Review preset changes."
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
                {analysis.new_presets.length}
              </div>
              <div className="text-xs text-green-600 font-medium">
                New Presets
              </div>
            </div>
            <div className="p-3 bg-blue-50 rounded-lg border border-blue-100">
              <div className="text-2xl font-bold text-blue-700">
                {analysis.updates.length}
              </div>
              <div className="text-xs text-blue-600 font-medium">
                Updates
              </div>
            </div>
            <div className="p-3 bg-gray-50 rounded-lg border border-gray-100 opacity-70">
              <div className="text-2xl font-bold text-gray-700">
                {analysis.duplicates.length}
              </div>
              <div className="text-xs text-gray-600 font-medium">
                Skipped (No Changes)
              </div>
            </div>
          </div>

          {analysis.updates.length > 0 && (
            <div className="space-y-2">
              <h4 className="text-sm font-medium">Update Preview</h4>
              <ScrollArea className="h-[150px] border rounded-md p-2 bg-muted/30">
                <div className="space-y-2 text-xs">
                  {analysis.updates.map((update, idx) => (
                    <div
                      key={idx}
                      className="flex flex-col gap-1 p-2 bg-background rounded border"
                    >
                      <div className="font-semibold">
                        {update.current.name}
                      </div>
                      <div className="text-muted-foreground truncate">
                        {update.current.description} -&gt; {update.new.description}
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
