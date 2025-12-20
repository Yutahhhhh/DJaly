import { useState, useEffect } from "react";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  Loader2,
  Sparkles,
  Music2,
} from "lucide-react";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { MultiSelect } from "@/components/ui/multi-select";
import { Track } from "@/types";
import { setlistsService } from "@/services/setlists";
import { presetsService, Preset } from "@/services/presets";
import { TrackRow } from "../TrackRow";

interface RecommendTabProps {
  referenceTrack: Track | null;
  availableGenres: string[];
  onAddTrack: (track: Track) => void;
  onPlay: (track: Track) => void;
  currentTrackId?: number | null;
}

export function RecommendTab({
  referenceTrack,
  availableGenres,
  onAddTrack,
  onPlay,
  currentTrackId,
}: RecommendTabProps) {
  const [recTracks, setRecTracks] = useState<Track[]>([]);
  const [isRecLoading, setIsRecLoading] = useState(false);
  const [recPresetId, setRecPresetId] = useState<number | null>(null);
  const [recPresets, setRecPresets] = useState<Preset[]>([]);
  const [recGenres, setRecGenres] = useState<string[]>([]);

  useEffect(() => {
    // Load presets for recommendation (using 'search' type or 'all' for now)
    presetsService.getAll("search").then(setRecPresets);
  }, []);

  useEffect(() => {
    if (referenceTrack) {
      fetchRecommendations();
    }
  }, [referenceTrack, recPresetId, recGenres]);

  const fetchRecommendations = async () => {
    if (!referenceTrack) return;
    setIsRecLoading(true);
    try {
      const data = await setlistsService.recommendNext(
        referenceTrack.id,
        recPresetId || undefined,
        recGenres.length > 0 ? recGenres : undefined
      );
      setRecTracks(data);
    } finally {
      setIsRecLoading(false);
    }
  };

  return (
    <div className="flex-1 flex flex-col p-0 m-0 min-h-0">
      <div className="p-3 bg-purple-50/50 dark:bg-purple-900/10 border-b shrink-0 space-y-3">
        {referenceTrack ? (
          <>
            <div className="text-sm">
              <div className="flex items-center gap-2 mb-1 text-purple-600 font-medium">
                <Sparkles className="h-4 w-4" />
                <span>Suggestions for:</span>
              </div>
              <div className="font-bold truncate bg-background p-2 rounded border shadow-sm">
                {referenceTrack.title}
              </div>
            </div>

            <div className="space-y-1">
              <label className="text-xs font-semibold text-muted-foreground">
                Suggestion Mode (Prompt)
              </label>
              <Select
                value={recPresetId?.toString() || "default"}
                onValueChange={(val) =>
                  setRecPresetId(val === "default" ? null : Number(val))
                }
              >
                <SelectTrigger className="h-8 text-xs bg-background">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="default">
                    🧬 Pure Vector (Default)
                  </SelectItem>
                  {recPresets.map((p) => (
                    <SelectItem key={p.id} value={p.id.toString()}>
                      ✨ {p.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div className="space-y-1">
              <label className="text-xs font-semibold text-muted-foreground">
                Filter by Genres
              </label>
              <MultiSelect
                options={availableGenres.map((g) => ({ label: g, value: g }))}
                selected={recGenres}
                onChange={setRecGenres}
                placeholder="All Genres"
                className="bg-background"
              />
            </div>
          </>
        ) : (
          <div className="text-sm text-muted-foreground text-center py-8 flex flex-col items-center gap-3">
            <Music2 className="h-10 w-10 opacity-20 dark:opacity-40" />
            <span className="max-w-[240px]">
              Select a track in the setlist to see recommendations.
            </span>
          </div>
        )}
      </div>

      <div className="flex-1 overflow-hidden">
        <ScrollArea className="h-full bg-background">
          {isRecLoading ? (
            <div className="flex justify-center p-8">
              <Loader2 className="animate-spin h-6 w-6 text-purple-500" />
            </div>
          ) : recTracks.length > 0 ? (
            <div className="pb-10">
              {recTracks.map((t) => (
                <TrackRow
                  key={`rec-${t.id}`}
                  id={`rec-${t.id}`}
                  track={t}
                  type="LIBRARY_ITEM"
                  isPlaying={currentTrackId === t.id}
                  onPlay={() => onPlay(t)}
                  onAdd={() => onAddTrack(t)}
                />
              ))}
            </div>
          ) : (
            referenceTrack && (
              <div className="text-center p-8 text-muted-foreground text-sm">
                No recommendations found for this mode.
              </div>
            )
          )}
        </ScrollArea>
      </div>
    </div>
  );
}
