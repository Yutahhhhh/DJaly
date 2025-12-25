import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Loader2 } from "lucide-react";
import { metadataService } from "@/services/metadata";

interface ArtworkFetcherProps {
  trackId: number;
  onArtworkFound: (dataUrl: string) => void;
  className?: string;
}

export function ArtworkFetcher({ trackId, onArtworkFound, className }: ArtworkFetcherProps) {
  const [loading, setLoading] = useState(false);

  const handleFetch = async () => {
    setLoading(true);
    try {
      const data = await metadataService.fetchArtworkInfo(trackId);
      if (data.info && data.info.startsWith("data:image")) {
        onArtworkFound(data.info);
      }
    } catch (e) {
      console.error("Artwork fetch failed:", e);
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
        <svg
          className="h-3 w-3 mr-1"
          viewBox="0 0 24 24"
          fill="currentColor"
          xmlns="http://www.w3.org/2000/svg"
        >
          <path d="M18.71 19.5c-.83 1.24-1.71 2.45-3.05 2.47-1.34.03-1.77-.79-3.29-.79-1.53 0-2 .77-3.27.82-1.31.05-2.3-1.32-3.14-2.53C4.25 17 2.94 12.45 4.7 9.39c.87-1.52 2.43-2.48 4.12-2.51 1.28-.02 2.5.87 3.29.87.78 0 2.26-1.07 3.81-.91.65.03 2.47.26 3.64 1.98-.09.06-2.17 1.28-2.15 3.81.03 3.02 2.65 4.03 2.68 4.04-.03.07-.42 1.44-1.38 2.83M13 3.5c.55-.67.92-1.56.81-2.43-.8.03-1.72.53-2.28 1.18-.51.58-.95 1.52-.81 2.41.89.07 1.75-.49 2.28-1.16z" />
        </svg>
      )}
      Get Artwork
    </Button>
  );
}
