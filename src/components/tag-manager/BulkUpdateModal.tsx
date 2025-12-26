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
import { Loader2, Check } from "lucide-react";

interface BulkUpdateModalProps {
  isOpen: boolean;
  onClose: () => void;
  type: "release_date" | "lyrics";
  trackIds?: number[];
}

export function BulkUpdateModal({ isOpen, onClose, type, trackIds }: BulkUpdateModalProps) {
  const { isUpdating, progress, statusText, currentTrack, stats, startUpdate, cancelUpdate, clearSkipCache } = useMetadata();
  const [overwrite, setOverwrite] = useState(false);
  const [clearingCache, setClearingCache] = useState(false);
  const [cacheCleared, setCacheCleared] = useState(false);

  const title = type === "release_date" ? "Auto-Fill Release Dates" : "Auto-Fill Lyrics";
  const description = type === "release_date" 
    ? "Fetch release dates from iTunes for all tracks." 
    : "Fetch lyrics from LRCLIB for all tracks.";

  const handleStart = () => {
    startUpdate(type, overwrite, trackIds);
  };

  const handleClearCache = async () => {
    setClearingCache(true);
    setCacheCleared(false);
    try {
      await clearSkipCache(type);
      setCacheCleared(true);
      setTimeout(() => {
        setCacheCleared(false);
      }, 2000);
    } finally {
      setClearingCache(false);
    }
  };

  return (
    <Dialog open={isOpen} onOpenChange={onClose}>
      <DialogContent className="sm:max-w-[425px]">
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          <DialogDescription>
            {description}
            {trackIds && !isUpdating && (
              <div className="mt-2 text-sm font-medium text-primary">
                Up to {trackIds.length} filtered tracks (excluding cached skips)
              </div>
            )}
            {isUpdating && stats.total > 0 && (
              <div className="mt-2 text-sm font-medium text-primary">
                Processing {stats.total} tracks
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
            <div className="pt-2 border-t">
              <Button 
                variant="outline" 
                size="sm" 
                onClick={handleClearCache}
                disabled={clearingCache || cacheCleared}
                className="w-full"
              >
                {clearingCache && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                {cacheCleared && <Check className="mr-2 h-4 w-4" />}
                {cacheCleared ? "Cache Cleared!" : "Clear Skip Cache"}
              </Button>
              <p className="text-xs text-muted-foreground mt-2">
                Remove cached "not found" tracks to retry fetching them.
              </p>
            </div>
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
