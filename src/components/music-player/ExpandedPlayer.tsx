import { useRef } from "react";
import {
  Minimize2,
  Sparkles,
  Save,
  FileText,
  Image as ImageIcon,
  Loader2,
  X,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { FileMetadata } from "@/services/metadata";
import { Track } from "@/types";
import { ArtworkFetcher } from "@/components/ui/ArtworkFetcher";
import { LyricsFetcher } from "@/components/ui/LyricsFetcher";
import { Lrc } from "react-lrc";

interface ExpandedPlayerProps {
  track: Track;
  metadata: FileMetadata | null;
  progress: number;
  editedLyrics: string;
  isEditingLyrics: boolean;
  isSaving: boolean;
  aiArtworkInfo: string | null;
  onClose: () => void;
  onApplyChanges: (updates: { lyrics?: string; artwork_data?: string }) => void;
  setEditedLyrics: (lyrics: string) => void;
  setIsEditingLyrics: (isEditing: boolean) => void;
  setAiArtworkInfo: (info: string | null) => void;
}

const hasTimeTags = (text: string) => {
  return /\[\d{2}:\d{2}\.\d{2,3}\]/.test(text);
};

export function ExpandedPlayer({
  track,
  metadata,
  progress,
  editedLyrics,
  isEditingLyrics,
  isSaving,
  aiArtworkInfo,
  onClose,
  onApplyChanges,
  setEditedLyrics,
  setIsEditingLyrics,
  setAiArtworkInfo,
}: ExpandedPlayerProps) {
  const fileInputRef = useRef<HTMLInputElement>(null);

  return (
    <div className="flex-1 flex flex-col overflow-hidden animate-in slide-in-from-bottom duration-500">
      <div className="flex justify-end p-1 border-b bg-muted/5">
        <Button
          variant="ghost"
          size="icon"
          className="h-6 w-6"
          onClick={onClose}
        >
          <Minimize2 className="h-4 w-4" />
        </Button>
      </div>
      <div className="flex-1 flex overflow-hidden px-6 py-4 gap-6">
        {/* Left Media Area */}
        <div className="w-1/3 h-full flex flex-col items-center justify-center border-r pr-6 border-border/40 relative">
          <div className="relative flex flex-col items-center gap-3">
            <div
              className="relative group w-32 h-32 bg-muted rounded-xl shadow-md overflow-hidden border-2 border-dashed border-primary/20 flex items-center justify-center cursor-pointer transition-all hover:border-primary/50 shrink-0"
              onClick={() => fileInputRef.current?.click()}
              onDragOver={(e) => e.preventDefault()}
              onDrop={async (e) => {
                e.preventDefault();
                const file = e.dataTransfer.files[0];
                if (file && file.type.startsWith("image/")) {
                  const reader = new FileReader();
                  reader.onload = (ev) => {
                    const b64 = (ev.target?.result as string).split(",")[1];
                    onApplyChanges({ artwork_data: b64 });
                  };
                  reader.readAsDataURL(file);
                }
              }}
            >
              {metadata?.artwork ? (
                <img
                  src={`data:image/jpeg;base64,${metadata.artwork}`}
                  className="w-full h-full object-cover"
                />
              ) : (
                <div className="text-center text-muted-foreground p-4">
                  <ImageIcon className="h-8 w-8 mx-auto mb-2 opacity-10" />
                  <p className="text-[10px] font-medium">画像をドロップ</p>
                </div>
              )}
              <div className="absolute inset-0 bg-black/60 opacity-0 group-hover:opacity-100 flex items-center justify-center transition-all backdrop-blur-sm">
                <Button variant="secondary" size="sm" className="h-7 text-xs">
                  変更
                </Button>
              </div>
            </div>

            <ArtworkFetcher
              trackId={track.id}
              onArtworkFound={(data) => setAiArtworkInfo(data)}
              className="rounded-full h-7 px-3 gap-1.5 text-[10px]"
            />

            {/* AI Suggestion Overlay */}
            {aiArtworkInfo && aiArtworkInfo.startsWith("data:image") && (
              <div className="absolute top-0 left-full ml-4 w-40 p-2 bg-background/95 backdrop-blur border rounded-xl shadow-2xl animate-in fade-in slide-in-from-left-4 duration-300 z-50">
                <div className="flex items-center justify-between mb-2">
                  <div className="flex items-center gap-1.5 text-primary font-bold text-[10px]">
                    <Sparkles className="h-3 w-3" /> AI Suggestion
                  </div>
                  <Button
                    variant="ghost"
                    size="icon"
                    className="h-4 w-4"
                    onClick={() => setAiArtworkInfo(null)}
                  >
                    <X className="h-3 w-3" />
                  </Button>
                </div>
                <img
                  src={aiArtworkInfo}
                  className="w-full aspect-square rounded-lg shadow-sm object-cover mb-2 bg-muted"
                />
                <Button
                  size="sm"
                  className="w-full h-6 text-[10px]"
                  onClick={() => {
                    const b64 = aiArtworkInfo.split(",")[1];
                    onApplyChanges({ artwork_data: b64 });
                    setAiArtworkInfo(null);
                  }}
                >
                  適用
                </Button>
              </div>
            )}
          </div>
        </div>

        {/* Right Lyrics Area */}
        <div className="flex-1 h-full flex flex-col">
          <div className="flex justify-between items-center mb-2">
            <h4 className="text-xs font-semibold flex items-center gap-1.5">
              <FileText className="h-3 w-3 text-primary" /> Lyrics
            </h4>
            <div className="flex gap-1.5">
              <LyricsFetcher 
                trackId={track.id}
                onLyricsFound={(lyrics) => setEditedLyrics(lyrics)}
                className="h-7 text-[10px]"
              />
              <Button
                size="sm"
                className="h-7 text-[10px]"
                onClick={() => onApplyChanges({ lyrics: editedLyrics })}
                disabled={isSaving || !editedLyrics}
              >
                {isSaving ? (
                  <Loader2 className="h-3 w-3 animate-spin mr-1" />
                ) : (
                  <Save className="h-3 w-3 mr-1" />
                )}
                保存
              </Button>
            </div>
          </div>
          
          {editedLyrics && !isEditingLyrics ? (
             hasTimeTags(editedLyrics) ? (
                <div className="flex-1 overflow-hidden bg-muted/5 rounded-md relative group">
                    <Lrc
                    lrc={editedLyrics}
                    currentMillisecond={progress * 1000}
                    lineRenderer={({ index, active, line }) => (
                        <div
                        key={index}
                        className={`text-center py-2 transition-all duration-300 px-4 ${
                            active 
                            ? "text-primary font-bold scale-105 blur-none" 
                            : "text-muted-foreground/60 blur-[0.5px] scale-95"
                        }`}
                        >
                        {line.content}
                        </div>
                    )}
                    className="h-full overflow-y-auto scroll-smooth no-scrollbar py-32"
                    />
                    <Button 
                        variant="secondary" 
                        size="sm" 
                        className="absolute top-2 right-2 h-6 text-[10px] opacity-0 group-hover:opacity-100 transition-opacity"
                        onClick={() => setIsEditingLyrics(true)}
                    >
                        編集
                    </Button>
                </div>
             ) : (
                <div className="flex-1 overflow-y-auto p-8 bg-muted/5 rounded-md relative group text-center whitespace-pre-wrap font-medium leading-loose text-muted-foreground">
                    {editedLyrics}
                    <Button 
                        variant="secondary" 
                        size="sm" 
                        className="absolute top-2 right-2 h-6 text-[10px] opacity-0 group-hover:opacity-100 transition-opacity"
                        onClick={() => setIsEditingLyrics(true)}
                    >
                        編集
                    </Button>
                </div>
             )
          ) : (
              <div className="flex-1 flex flex-col relative">
                  <div className="text-[10px] text-muted-foreground mb-1 px-1">
                    Raw LRC Editor (Time tags required for sync)
                  </div>
                  <Textarea
                    value={editedLyrics}
                    onChange={(e) => setEditedLyrics(e.target.value)}
                    className="flex-1 font-mono text-xs leading-relaxed p-4 bg-muted/5 resize-none border-none focus-visible:ring-0"
                    placeholder="[00:00.00] Lyrics..."
                  />
                  {editedLyrics && (
                    <Button 
                        variant="ghost" 
                        size="sm" 
                        className="absolute top-2 right-2 h-6 text-[10px]"
                        onClick={() => setIsEditingLyrics(false)}
                    >
                        プレビュー
                    </Button>
                  )}
              </div>
          )}
        </div>
      </div>
      
      <input
        type="file"
        ref={fileInputRef}
        className="hidden"
        accept="image/*"
        onChange={(e) => {
          const file = e.target.files?.[0];
          if (file) {
            const reader = new FileReader();
            reader.onload = (ev) =>
              onApplyChanges({
                artwork_data: (ev.target?.result as string).split(",")[1],
              });
            reader.readAsDataURL(file);
          }
        }}
      />
    </div>
  );
}
