import { useState, useEffect } from "react";
import { TagCategory } from "./TagManager";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
import { Save, Loader2 } from "lucide-react";
import { tracksService } from "@/services/tracks";
import { metadataService } from "@/services/metadata";
import { ArtworkFetcher } from "@/components/ui/ArtworkFetcher";
import { LyricsFetcher } from "@/components/ui/LyricsFetcher";

interface TagEditorProps {
  category: TagCategory;
  selectedItem: any;
}

export function TagEditor({ category, selectedItem }: TagEditorProps) {
  const [formData, setFormData] = useState<any>({});
  const [saving, setSaving] = useState(false);
  const [loading, setLoading] = useState(false);
  const [artwork, setArtwork] = useState<string | null>(null);

  useEffect(() => {
    if (selectedItem) {
      if (category === "track-info") {
        setFormData({
          title: selectedItem.title,
          artist: selectedItem.artist,
          album: selectedItem.album,
          year: selectedItem.year,
        });
        fetchMetadata(selectedItem.id);
      } else if (category === "lyrics") {
        fetchLyrics(selectedItem.id);
      } else {
        // Genre/Subgenre
      }
    }
  }, [selectedItem, category]);

  const fetchMetadata = async (trackId: number) => {
    try {
      const data = await metadataService.getMetadata(trackId);
      setArtwork(data.artwork);
    } catch (e) {
      console.error(e);
    }
  };

  const fetchLyrics = async (trackId: number) => {
    setLoading(true);
    try {
      const data = await metadataService.getLyricsFromDB(trackId);
      setFormData({ lyrics: data.content || "" });
    } catch (e) {
      console.error(e);
      // If 404, it means no lyrics yet
      setFormData({ lyrics: "" });
    } finally {
      setLoading(false);
    }
  };

  const handleSave = async () => {
    if (!selectedItem) return;
    setSaving(true);
    try {
      if (category === "track-info") {
        await tracksService.updateTrackInfo(selectedItem.id, {
          title: formData.title,
          artist: formData.artist,
          album: formData.album,
          year: formData.year,
        });
        if (formData.artwork_data) {
          await metadataService.updateMetadata(selectedItem.id, { artwork_data: formData.artwork_data });
        }
      } else if (category === "lyrics") {
        await metadataService.updateLyricsInDB(selectedItem.id, formData.lyrics);
      }
      // Show success toast?
    } catch (e) {
      console.error(e);
    } finally {
      setSaving(false);
    }
  };

  if (!selectedItem) {
    return (
      <div className="flex-1 flex items-center justify-center text-muted-foreground bg-muted/5">
        Select an item to edit
      </div>
    );
  }

  return (
    <div className="flex-1 flex flex-col bg-background p-6 space-y-6">
      <div className="flex justify-between items-start">
        <div>
          <h2 className="text-2xl font-bold">{selectedItem.label || selectedItem.title}</h2>
          <p className="text-muted-foreground text-sm">
            {category === "track-info" ? "Edit track metadata" : 
             category === "lyrics" ? "Edit lyrics" : 
             `Manage ${category}`}
          </p>
        </div>
        <div className="flex gap-2">
          <Button onClick={handleSave} disabled={saving}>
            {saving ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Save className="mr-2 h-4 w-4" />}
            Save
          </Button>
        </div>
      </div>

      <div className="flex-1 overflow-auto">
        {loading ? (
          <div className="flex justify-center p-10">
            <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
          </div>
        ) : (
          <>
            {category === "track-info" && (
              <div className="space-y-4 max-w-xl">
                <div className="flex items-start gap-6 p-4 border rounded-lg bg-muted/10">
                    <div className="w-32 h-32 bg-muted rounded-md overflow-hidden flex items-center justify-center border shrink-0 relative group">
                        {artwork ? (
                            <img src={`data:image/jpeg;base64,${artwork}`} className="w-full h-full object-cover" />
                        ) : (
                            <span className="text-xs text-muted-foreground">No Artwork</span>
                        )}
                        {formData.artwork_data && (
                             <div className="absolute inset-0 bg-black/50 flex items-center justify-center text-white text-xs font-bold">
                                 New (Unsaved)
                             </div>
                        )}
                    </div>
                    <div className="flex flex-col gap-3">
                        <div className="space-y-1">
                            <h3 className="font-medium text-sm">Artwork</h3>
                            <p className="text-xs text-muted-foreground">Fetch from Apple Music.</p>
                        </div>
                        <ArtworkFetcher 
                            trackId={selectedItem.id} 
                            onArtworkFound={(data) => {
                                const b64 = data.split(",")[1];
                                setArtwork(b64);
                                setFormData((prev: any) => ({ ...prev, artwork_data: b64 }));
                            }}
                        />
                    </div>
                </div>

                <div className="grid gap-2">
                  <Label>Title</Label>
                  <Input 
                    value={formData.title || ""} 
                    onChange={e => setFormData({...formData, title: e.target.value})} 
                  />
                </div>
                <div className="grid gap-2">
                  <Label>Artist</Label>
                  <Input 
                    value={formData.artist || ""} 
                    onChange={e => setFormData({...formData, artist: e.target.value})} 
                  />
                </div>
                <div className="grid gap-2">
                  <Label>Album</Label>
                  <Input 
                    value={formData.album || ""} 
                    onChange={e => setFormData({...formData, album: e.target.value})} 
                  />
                </div>
                <div className="grid gap-2">
                  <Label>Year</Label>
                  <Input 
                    type="number"
                    value={formData.year || ""} 
                    onChange={e => setFormData({...formData, year: parseInt(e.target.value)})} 
                  />
                </div>
              </div>
            )}

            {category === "lyrics" && (
              <div className="h-full flex flex-col gap-2">
                <div className="flex justify-end">
                  <LyricsFetcher 
                    trackId={selectedItem.id}
                    onLyricsFound={(lyrics) => setFormData({ ...formData, lyrics })}
                  />
                </div>
                <Textarea 
                  className="flex-1 font-mono resize-none"
                  value={formData.lyrics || ""}
                  onChange={e => setFormData({...formData, lyrics: e.target.value})}
                  placeholder="Enter lyrics here..."
                />
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}
