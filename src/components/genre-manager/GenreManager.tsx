import React, { useState } from "react";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Button } from "@/components/ui/button";
import { Save } from "lucide-react";
import { genreService } from "@/services/genres";
import { AnalyzeMissingTab } from "./AnalyzeMissingTab";
import { SuggestionsTab } from "./SuggestionsTab";
import { CleanupTab } from "./CleanupTab";
import { Track } from "@/types";

interface GenreManagerProps {
  onPlay: (track: Track) => void;
}

export const GenreManager: React.FC<GenreManagerProps> = ({ onPlay }) => {
  const [isApplying, setIsApplying] = useState(false);

  const handleApplyToFiles = async () => {
    if (!confirm("Are you sure you want to write DB genres to ALL file tags? This cannot be undone.")) {
      return;
    }
    
    setIsApplying(true);
    try {
      const result = await genreService.applyGenresToFiles([]);
      alert(`Applied genres to files.\nSuccess: ${result.success}\nFailed: ${result.failed}`);
    } catch (error) {
      console.error(error);
      alert("Failed to apply genres to files.");
    } finally {
      setIsApplying(false);
    }
  };

  return (
    <div className="h-full flex flex-col p-6 space-y-6">
      <div className="flex justify-between items-start">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Genre Manager</h1>
          <p className="text-muted-foreground">
            Manage and organize your music library genres using AI and similarity
            analysis.
          </p>
        </div>
        <Button 
          onClick={handleApplyToFiles} 
          disabled={isApplying}
          variant="outline"
        >
          <Save className="mr-2 h-4 w-4" />
          {isApplying ? "Applying..." : "Sync to Files"}
        </Button>
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
            <CleanupTab onPlay={onPlay} />
          </TabsContent>
          <TabsContent
            value="missing"
            className="flex-1 p-0 m-0 min-h-0 data-[state=inactive]:hidden"
          >
            <AnalyzeMissingTab onPlay={onPlay} />
          </TabsContent>
          <TabsContent
            value="suggestions"
            className="flex-1 p-0 m-0 min-h-0 data-[state=inactive]:hidden"
          >
            <SuggestionsTab onPlay={onPlay} />
          </TabsContent>
        </div>
      </Tabs>
    </div>
  );
};
