import React from "react";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { AnalyzeMissingTab } from "./AnalyzeMissingTab";
import { SuggestionsTab } from "./SuggestionsTab";
import { CleanupTab } from "./CleanupTab";
import { Track } from "@/types";

import { AnalysisMode } from "@/services/genres";

interface GenreManagerProps {
  onPlay: (track: Track) => void;
  mode: AnalysisMode;
}

export const GenreManager: React.FC<GenreManagerProps> = ({ onPlay, mode }) => {
  const title = mode === "genre" ? "Genre Manager" : mode === "subgenre" ? "Subgenre Manager" : "Genre & Subgenre Manager";

  return (
    <div className="h-full flex flex-col p-6 space-y-6">
      <div className="flex justify-between items-start">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">{title}</h1>
          <p className="text-muted-foreground">
            Manage and organize your music library {mode}s using AI and similarity analysis.
          </p>
        </div>
      </div>

      <Tabs defaultValue="cleanup" className="flex-1 flex flex-col min-h-0">
        <TabsList>
          <TabsTrigger value="cleanup">Cleanup</TabsTrigger>
          <TabsTrigger value="missing">Analyze Missing</TabsTrigger>
          <TabsTrigger value="suggestions">Suggestions</TabsTrigger>
        </TabsList>

        <div className="flex-1 mt-4 border rounded-lg bg-background/50 flex flex-col min-h-0 overflow-hidden">
          <TabsContent
            value="cleanup"
            className="flex-1 p-0 m-0 min-h-0 data-[state=inactive]:hidden"
          >
            <CleanupTab onPlay={onPlay} mode={mode} />
          </TabsContent>
          <TabsContent
            value="missing"
            className="flex-1 p-0 m-0 min-h-0 data-[state=inactive]:hidden"
          >
            <AnalyzeMissingTab onPlay={onPlay} mode={mode} />
          </TabsContent>
          <TabsContent
            value="suggestions"
            className="flex-1 p-0 m-0 min-h-0 data-[state=inactive]:hidden"
          >
            <SuggestionsTab onPlay={onPlay} mode={mode} />
          </TabsContent>
        </div>
      </Tabs>
    </div>
  );
};
