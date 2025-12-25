import { useState } from "react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Label } from "@/components/ui/label";
import { Progress } from "@/components/ui/progress";
import { useMetadata } from "@/contexts/MetadataContext";

interface BulkUpdateModalProps {
  isOpen: boolean;
  onClose: () => void;
  type: "release_date" | "lyrics";
  trackIds?: number[];
}

export function BulkUpdateModal({ isOpen, onClose, type, trackIds }: BulkUpdateModalProps) {
  const { isUpdating, progress, statusText, currentTrack, stats, startUpdate, cancelUpdate } = useMetadata();
  const [overwrite, setOverwrite] = useState(false);

  const title = type === "release_date" ? "Auto-Fill Release Dates" : "Auto-Fill Lyrics";
  const description = type === "release_date" 
    ? "Fetch release dates from iTunes for all tracks." 
    : "Fetch lyrics from LRCLIB for all tracks.";

  const handleStart = () => {
    startUpdate(type, overwrite, trackIds);
  };

  return (
    <Dialog open={isOpen} onOpenChange={onClose}>
      <DialogContent className="sm:max-w-[425px]">
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          <DialogDescription>
            {description}
            {trackIds && (
              <div className="mt-2 text-sm font-medium text-primary">
                Targeting {trackIds.length} filtered tracks.
              </div>
            )}
          </DialogDescription>
        </DialogHeader>

        {!isUpdating ? (
          <div className="grid gap-4 py-4">
            <div className="flex items-center space-x-2">
              <Checkbox 
                id="overwrite" 
                checked={overwrite} 
                onCheckedChange={(c) => setOverwrite(!!c)} 
              />
              <Label htmlFor="overwrite">Overwrite existing values</Label>
            </div>
            <p className="text-sm text-muted-foreground">
              {overwrite 
                ? "Existing data will be replaced." 
                : "Only tracks with missing data will be updated."}
            </p>
          </div>
        ) : (
          <div className="grid gap-4 py-4 w-full">
            <div className="space-y-2 w-full min-w-0">
              <div className="flex justify-between text-sm w-full">
                <span className="truncate pr-2 flex-1 min-w-0">{statusText}</span>
                <span className="shrink-0">{Math.round(progress)}%</span>
              </div>
              <Progress value={progress} />
              <div className="text-xs text-muted-foreground truncate w-full min-h-5 min-w-0" title={currentTrack}>
                {currentTrack}
              </div>
              <div className="grid grid-cols-3 gap-2 text-xs text-center mt-2">
                <div className="bg-muted p-2 rounded">
                  <div className="font-bold">{stats.updated}</div>
                  <div className="text-muted-foreground">Updated</div>
                </div>
                <div className="bg-muted p-2 rounded">
                  <div className="font-bold">{stats.skipped}</div>
                  <div className="text-muted-foreground">Skipped</div>
                </div>
                <div className="bg-muted p-2 rounded">
                  <div className="font-bold">{stats.errors}</div>
                  <div className="text-muted-foreground">Errors</div>
                </div>
              </div>
            </div>
          </div>
        )}

        <DialogFooter>
          {!isUpdating ? (
            <>
              <Button variant="outline" onClick={onClose}>Cancel</Button>
              <Button onClick={handleStart}>Start Update</Button>
            </>
          ) : (
            <>
              <Button variant="outline" onClick={onClose}>Background</Button>
              <Button variant="destructive" onClick={cancelUpdate}>
                Stop
              </Button>
            </>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
