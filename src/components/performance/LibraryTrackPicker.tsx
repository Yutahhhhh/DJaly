import { useEffect, useState, type FormEvent } from "react";
import { Loader2, Search } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { ScrollArea } from "@/components/ui/scroll-area";
import { tracksService } from "@/services/tracks";
import type { Track } from "@/types";
import type { DeckId } from "@/types/dj-engine";

interface LibraryTrackPickerProps {
  deck: DeckId | null;
  onClose: () => void;
  onSelect: (track: Track) => void | Promise<void>;
}

export function LibraryTrackPicker({ deck, onClose, onSelect }: LibraryTrackPickerProps) {
  const [query, setQuery] = useState("");
  const [tracks, setTracks] = useState<Track[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selecting, setSelecting] = useState(false);

  const search = async (q = query) => {
    setLoading(true);
    setError(null);
    try {
      setTracks(await tracksService.getTracks({ q: q.trim() || undefined, limit: 100 }));
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : String(failure));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (deck) {
      setSelecting(false);
      void search("");
    }
    // Opening a deck picker is the intentional refresh boundary.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [deck]);

  const submit = (event: FormEvent) => {
    event.preventDefault();
    void search();
  };

  return (
    <Dialog open={deck !== null} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-w-3xl">
        <DialogHeader>
          <DialogTitle>Load library track into Deck {deck}</DialogTitle>
          <DialogDescription>
            plumdeck remains the source of truth; the native engine receives a temporary descriptor.
          </DialogDescription>
        </DialogHeader>
        <form className="flex gap-2" onSubmit={submit}>
          <Input
            autoFocus
            aria-label="Search library"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Title, artist, album, genre…"
          />
          <Button type="submit" disabled={loading}>
            {loading ? <Loader2 className="animate-spin" /> : <Search />}
            Search
          </Button>
        </form>
        {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
        <ScrollArea className="h-[52vh] rounded-lg border">
          <div className="divide-y">
            {!loading && tracks.length === 0 && (
              <p className="p-8 text-center text-sm text-muted-foreground">No tracks found.</p>
            )}
            {tracks.map((track) => {
              const loadable = Boolean(track.filepath && track.duration > 0);
              return (
                <button
                  key={track.id}
                  type="button"
                  disabled={!loadable || selecting}
                  onClick={() => {
                    setSelecting(true);
                    void Promise.resolve(onSelect(track)).catch((failure) => {
                      setError(failure instanceof Error ? failure.message : String(failure));
                      setSelecting(false);
                    });
                  }}
                  className="grid w-full grid-cols-[minmax(0,1fr)_auto] gap-4 p-3 text-left transition-colors hover:bg-muted/60 disabled:cursor-not-allowed disabled:opacity-40"
                >
                  <span className="min-w-0">
                    <span className="block truncate text-sm font-medium">{track.title || track.filepath}</span>
                    <span className="block truncate text-xs text-muted-foreground">
                      {track.artist || "Unknown artist"} · {track.album || "Unknown album"}
                    </span>
                  </span>
                  <span className="self-center font-mono text-xs text-muted-foreground">
                    {track.bpm ? `${track.bpm.toFixed(1)} BPM` : "—"}
                  </span>
                </button>
              );
            })}
          </div>
        </ScrollArea>
      </DialogContent>
    </Dialog>
  );
}
