import { useState, useEffect } from "react";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Track } from "@/types";
import { genreService } from "@/services/genres";
import { LibraryTab } from "./tabs/LibraryTab";
import { RecommendTab } from "./tabs/RecommendTab";
import { AutoTab } from "./tabs/AutoTab";

interface TrackSelectorProps {
  referenceTrack: Track | null;
  onAddTrack: (track: Track) => void;
  onInjectTracks: (tracks: Track[], startId?: number, endId?: number) => void; // ★ 追加
  currentSetlistTracks: Track[];
  onPlay: (track: Track) => void;
  currentTrackId?: number | null;
}

export function TrackSelector({
  referenceTrack,
  onAddTrack,
  onInjectTracks, // ★
  currentSetlistTracks,
  onPlay,
  currentTrackId,
}: TrackSelectorProps) {
  const [activeTab, setActiveTab] = useState("library");
  const [availableGenres, setAvailableGenres] = useState<string[]>([]);

  useEffect(() => {
    genreService.getAllGenres().then(setAvailableGenres).catch(console.error);
  }, []);

  return (
    <div className="w-[400px] border-l bg-background flex flex-col shadow-xl z-20 h-full">
      <Tabs
        value={activeTab}
        onValueChange={setActiveTab}
        className="flex-1 flex flex-col min-h-0"
      >
        <div className="p-2 border-b bg-muted/20 shrink-0">
          <TabsList className="w-full grid grid-cols-3">
            <TabsTrigger value="library" className="text-xs">
              Library
            </TabsTrigger>
            <TabsTrigger value="recommend" className="text-xs">
              Recommend
            </TabsTrigger>
            <TabsTrigger value="auto" className="text-xs">
              Auto Gen
            </TabsTrigger>
          </TabsList>
        </div>

        {/* --- Library Tab --- */}
        <TabsContent
          value="library"
          className="flex-1 flex flex-col p-0 m-0 min-h-0 data-[state=active]:flex"
        >
          <LibraryTab
            onAddTrack={onAddTrack}
            onPlay={onPlay}
            currentTrackId={currentTrackId}
          />
        </TabsContent>

        {/* --- Recommend Tab --- */}
        <TabsContent
          value="recommend"
          className="flex-1 flex flex-col p-0 m-0 min-h-0 data-[state=active]:flex"
        >
          <RecommendTab
            referenceTrack={referenceTrack}
            availableGenres={availableGenres}
            onAddTrack={onAddTrack}
            onPlay={onPlay}
            currentTrackId={currentTrackId}
          />
        </TabsContent>

        {/* --- Auto Tab --- */}
        <TabsContent
          value="auto"
          className="flex-1 flex flex-col p-0 m-0 min-h-0 data-[state=active]:flex"
        >
          <AutoTab
            currentSetlistTracks={currentSetlistTracks}
            availableGenres={availableGenres}
            onInjectTracks={onInjectTracks} // ★
            onPlay={onPlay}
            currentTrackId={currentTrackId}
          />
        </TabsContent>
      </Tabs>
    </div>
  );
}
