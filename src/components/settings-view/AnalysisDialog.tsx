import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Loader2 } from "lucide-react";
import { cn } from "@/lib/utils";

interface AnalysisDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  description: string;
  isAnalyzing: boolean;
  isImporting: boolean;
  onExecute: () => void;
  canExecute: boolean;
  children: React.ReactNode;
  className?: string;
}

export function AnalysisDialog({
  open,
  onOpenChange,
  title,
  description,
  isAnalyzing,
  isImporting,
  onExecute,
  canExecute,
  children,
  className,
}: AnalysisDialogProps) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className={cn("max-w-2xl max-h-[80vh] flex flex-col", className)}>
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          <DialogDescription>{description}</DialogDescription>
        </DialogHeader>

        {isAnalyzing ? (
          <div className="py-8 flex flex-col items-center gap-4">
            <Loader2 className="h-8 w-8 animate-spin text-primary" />
            <p className="text-sm text-muted-foreground">Analyzing...</p>
          </div>
        ) : (
          <div className="flex-1 overflow-hidden flex flex-col gap-4">
             {children}
          </div>
        )}

        <DialogFooter>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button
            onClick={onExecute}
            disabled={isAnalyzing || isImporting || !canExecute}
          >
            {isImporting && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
            Execute Import
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
