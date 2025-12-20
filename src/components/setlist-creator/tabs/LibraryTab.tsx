import { useState, useEffect } from "react";
import { Input } from "@/components/ui/input";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Search, Loader2 } from "lucide-react";
import { Track } from "@/types";
import { tracksService } from "@/services/tracks";
import { TrackRow } from "../TrackRow";

export function LibraryTab({ onPlay, currentTrackId }: any) {
  const [query, setQuery] = useState("");
  const [tracks, setTracks] = useState<Track[]>([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    const t = setTimeout(search, 300);
    return () => clearTimeout(t);
  }, [query]);

  const search = async () => {
    setLoading(true);
    try {
      const data = await tracksService.getTracks({ title: query, limit: 50 });
      setTracks(data);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex-1 flex flex-col min-h-0 bg-background">
      <div className="p-2 border-b">
        <div className="relative">
          <Search className="absolute left-2 top-2.5 h-4 w-4 text-muted-foreground" />
          <Input
            className="pl-8 h-9 text-xs"
            placeholder="Search tracks..."
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </div>
      </div>
      <ScrollArea className="flex-1">
        {loading ? (
          <div className="p-8 flex justify-center">
            <Loader2 className="animate-spin h-6 w-6 opacity-20" />
          </div>
        ) : (
          <div className="p-2 space-y-1">
            {tracks.map((t) => (
              <TrackRow
                key={`lib-${t.id}`}
                id={`lib-${t.id}`}
                track={t}
                type="LIBRARY_ITEM"
                isPlaying={currentTrackId === t.id}
                onPlay={() => onPlay(t)}
              />
            ))}
          </div>
        )}
      </ScrollArea>
    </div>
  );
}
