import { useState } from "react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { Info, Tags, Mic2, Music, Save, Loader2, Wand2 } from "lucide-react";
import { TagCategory } from "./TagManager";
import { genreService } from "@/services/genres";
import { BulkUpdateModal } from "./BulkUpdateModal";
import { tracksService } from "@/services/tracks";
import { buildTrackSearchParams } from "@/components/music-library/utils";

interface TagSidebarProps {
  activeCategory: TagCategory;
  onSelectCategory: (category: TagCategory) => void;
  trackSearch?: any;
  extraParams?: any;
}

export function TagSidebar({ activeCategory, onSelectCategory, trackSearch, extraParams }: TagSidebarProps) {
  const [isSyncing, setIsSyncing] = useState(false);
  const [showBulkModal, setShowBulkModal] = useState(false);
  const [bulkType, setBulkType] = useState<"release_date" | "lyrics">("release_date");
  const [filteredTrackIds, setFilteredTrackIds] = useState<number[] | undefined>(undefined);
  const [isFetchingIds, setIsFetchingIds] = useState(false);

  const handleSyncToFiles = async () => {
    if (!confirm("Are you sure you want to write DB metadata to ALL file tags? This cannot be undone.")) {
      return;
    }
    
    setIsSyncing(true);
    try {
      const result = await genreService.applyGenresToFiles([]);
      alert(`Applied metadata to files.\nSuccess: ${result.success}\nFailed: ${result.failed}`);
    } catch (error) {
      console.error(error);
      alert("Failed to apply metadata to files.");
    } finally {
      setIsSyncing(false);
    }
  };

  const openBulkModal = async (type: "release_date" | "lyrics") => {
    setBulkType(type);
    
    // If we have search context, fetch all matching IDs
    if (trackSearch) {
      setIsFetchingIds(true);
      try {
        const params = buildTrackSearchParams(trackSearch.query, trackSearch.filters, 100000, 0); // High limit to get all
        const finalParams = { ...params, ...extraParams };
        const ids = await tracksService.getTrackIds(finalParams);
        setFilteredTrackIds(ids);
        setShowBulkModal(true);
      } catch (error) {
        console.error("Failed to fetch filtered track IDs", error);
        alert("Failed to prepare bulk update. Please try again.");
      } finally {
        setIsFetchingIds(false);
      }
    } else {
      setFilteredTrackIds(undefined);
      setShowBulkModal(true);
    }
  };

  const categories: { id: TagCategory; label: string; icon: any; group?: string }[] = [
    { id: "track-info", label: "Track Info", icon: Info, group: "Metadata" },
    { id: "lyrics", label: "Lyrics", icon: Mic2, group: "Metadata" },
    
    { id: "genre", label: "Genre", icon: Music, group: "Classification" },
    { id: "subgenre", label: "SubGenre", icon: Tags, group: "Classification" },
  ];

  // Group categories
  const grouped = categories.reduce((acc, cat) => {
    const group = cat.group || "Other";
    if (!acc[group]) acc[group] = [];
    acc[group].push(cat);
    return acc;
  }, {} as Record<string, typeof categories>);

  return (
    <div className="w-64 border-r bg-muted/10 flex flex-col shrink-0">
      <div className="p-4 font-semibold text-lg border-b">Tags & Metadata</div>
      <div className="flex-1 p-2 space-y-6 overflow-y-auto">
        {Object.entries(grouped).map(([group, items]) => (
          <div key={group} className="space-y-1">
            <h3 className="px-2 text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-2">
              {group}
            </h3>
            {items.map((cat) => (
              <Button
                key={cat.id}
                variant={activeCategory === cat.id ? "secondary" : "ghost"}
                className={cn(
                  "w-full justify-start gap-2",
                  activeCategory === cat.id && "bg-secondary"
                )}
                onClick={() => onSelectCategory(cat.id)}
              >
                <cat.icon className="h-4 w-4" />
                {cat.label}
              </Button>
            ))}
          </div>
        ))}
      </div>

      <div className="p-4 border-t mt-auto space-y-2">
        {activeCategory === "track-info" && (
          <Button 
            variant="outline" 
            className="w-full justify-start gap-2"
            onClick={() => openBulkModal("release_date")}
            disabled={isFetchingIds}
          >
            {isFetchingIds ? <Loader2 className="h-4 w-4 animate-spin" /> : <Wand2 className="h-4 w-4" />}
            Auto-Fill Dates
          </Button>
        )}

        {activeCategory === "lyrics" && (
          <Button 
            variant="outline" 
            className="w-full justify-start gap-2"
            onClick={() => openBulkModal("lyrics")}
            disabled={isFetchingIds}
          >
            {isFetchingIds ? <Loader2 className="h-4 w-4 animate-spin" /> : <Wand2 className="h-4 w-4" />}
            Auto-Fill Lyrics
          </Button>
        )}

        <Button 
          variant="outline" 
          className="w-full justify-start gap-2"
          onClick={handleSyncToFiles}
          disabled={isSyncing}
        >
          {isSyncing ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
          Sync to Files
        </Button>
      </div>

      <BulkUpdateModal 
        isOpen={showBulkModal} 
        onClose={() => setShowBulkModal(false)} 
        type={bulkType}
        trackIds={filteredTrackIds}
      />
    </div>
  );
}
