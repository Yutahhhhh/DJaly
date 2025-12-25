import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Loader2, Sparkles } from "lucide-react";
import { metadataService } from "@/services/metadata";

interface LyricsFetcherProps {
  trackId: number;
  onLyricsFound: (lyrics: string) => void;
  className?: string;
}

export function LyricsFetcher({ trackId, onLyricsFound, className }: LyricsFetcherProps) {
  const [loading, setLoading] = useState(false);

  const handleFetch = async () => {
    setLoading(true);
    try {
      const data = await metadataService.fetchLyricsSingle(trackId);
      if (data.lyrics) {
        onLyricsFound(data.lyrics);
      }
    } catch (e) {
      console.error("Lyrics fetch failed:", e);
    } finally {
      setLoading(false);
    }
  };

  return (
    <Button
      variant="outline"
      size="sm"
      className={className}
      onClick={handleFetch}
      disabled={loading}
    >
      {loading ? (
        <Loader2 className="h-3 w-3 animate-spin mr-1" />
      ) : (
        <Sparkles className="h-3 w-3 mr-1" />
      )}
      Auto-Fill
    </Button>
  );
}
