import { useState, useEffect, useRef } from "react";
import {
  Pause,
  Play,
  SkipBack,
  SkipForward,
  Volume2,
  X,
  Minimize2,
  Maximize2,
  Sparkles,
  Save,
  FileText,
  Image as ImageIcon,
  Loader2,
  Music,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Slider } from "@/components/ui/slider";
import { API_BASE_URL } from "@/services/api-client";
import { metadataService, FileMetadata } from "@/services/metadata";
import { formatTime } from "@/lib/utils";
import { Track } from "@/types";

interface MusicPlayerProps {
  track: Track | null;
  onClose: () => void;
  onLoadingChange?: (isLoading: boolean) => void;
  autoPlay?: boolean;
}

export function MusicPlayer({
  track,
  onClose,
  onLoadingChange,
  autoPlay = true,
}: MusicPlayerProps) {
  const [isPlaying, setIsPlaying] = useState(false);
  const [isExpanded, setIsExpanded] = useState(false);
  const [metadata, setMetadata] = useState<FileMetadata | null>(null);
  const [editedLyrics, setEditedLyrics] = useState("");
  const [isAIFetching, setIsAIFetching] = useState<string | null>(null);
  const [aiArtworkInfo, setAiArtworkInfo] = useState<string | null>(null);
  const [isSaving, setIsSaving] = useState(false);
  const [volume, setVolume] = useState(0.8);
  const [progress, setProgress] = useState(0);

  const audioRef = useRef<HTMLAudioElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);

  // 波形の描画
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const width = canvas.width;
    const height = canvas.height;
    ctx.clearRect(0, 0, width, height);

    // CSS変数の値を取得して色を構築
    const rootStyles = getComputedStyle(document.documentElement);
    const primaryVal = rootStyles.getPropertyValue("--primary").trim();
    const mutedVal = rootStyles.getPropertyValue("--muted-foreground").trim();
    
    // Canvasでは var() が使えないため、直接値を埋め込む
    // Tailwindの変数は通常 "H S L" の形式 (カンマなし)
    const primaryColor = `hsl(${primaryVal})`;
    const mutedColor = `hsla(${mutedVal.split(" ").join(",")}, 0.3)`;

    if (!metadata?.waveform_peaks || metadata.waveform_peaks.length === 0) {
      // 波形がない場合は単純なプログレスバーを描画
      ctx.fillStyle = `hsla(${mutedVal.split(" ").join(",")}, 0.2)`;
      ctx.fillRect(0, height / 2 - 1, width, 2);
      
      const progressWidth = (progress / (audioRef.current?.duration || 1)) * width;
      ctx.fillStyle = primaryColor;
      ctx.fillRect(0, height / 2 - 1, progressWidth, 2);
      return;
    }

    const peaks = metadata.waveform_peaks;
    const barWidth = 3;
    const gap = 1;
    const totalBars = Math.floor(width / (barWidth + gap));
    const step = Math.ceil(peaks.length / totalBars);
    const currentRatio = progress / (audioRef.current?.duration || 1);

    for (let i = 0; i < totalBars; i++) {
      const peakIndex = Math.floor(i * step);
      const value = peaks[peakIndex] || 0;
      const barHeight = Math.max(value * height * 0.8, 2); // 最小高さを確保
      const x = i * (barWidth + gap);
      const y = (height - barHeight) / 2;

      if (x / width < currentRatio) {
        ctx.fillStyle = primaryColor;
      } else {
        ctx.fillStyle = mutedColor;
      }

      ctx.fillRect(x, y, barWidth, barHeight);
    }
  }, [metadata, progress, isExpanded]);

  // 楽曲の読み込みとメタデータの取得
  useEffect(() => {
    if (track) {
      onLoadingChange?.(true);
      setMetadata(null);
      setAiArtworkInfo(null);
      setProgress(0);

      if (audioRef.current) {
        audioRef.current.src = `${API_BASE_URL}/stream?path=${encodeURIComponent(
          track.filepath
        )}`;
        if (autoPlay) {
          audioRef.current.play().catch(() => {});
          setIsPlaying(true);
        }
      }

      // サービス層を使用してメタデータを取得
      metadataService
        .getMetadata(track.id)
        .then((data) => {
          setMetadata(data);
          setEditedLyrics(data.lyrics || "");
        })
        .finally(() => onLoadingChange?.(false));
    } else {
      setIsPlaying(false);
    }
  }, [track, autoPlay]);

  // ファイルメタデータの更新適用
  const handleApplyChanges = async (updates: {
    lyrics?: string;
    artwork_data?: string;
  }) => {
    if (!track) return;
    setIsSaving(true);
    try {
      await metadataService.updateMetadata(track.id, updates);
      // 更新後に最新状態を再ロード
      const updated = await metadataService.getMetadata(track.id);
      setMetadata(updated);
    } catch (e) {
      console.error("Failed to apply metadata updates:", e);
    } finally {
      setIsSaving(false);
    }
  };

  // 個別コンテンツのAIフェッチ
  const handleAIFetch = async (
    target: "lyrics" | "artwork_info"
  ) => {
    if (!track) return;
    setIsAIFetching(target);
    try {
      if (target === "lyrics") {
        const data = await metadataService.fetchLyrics(track.id);
        setEditedLyrics(data.lyrics);
      } else if (target === "artwork_info") {
        const data = await metadataService.fetchArtworkInfo(track.id);
        setAiArtworkInfo(data.info);
      }
    } catch (e) {
      console.error(`AI Fetch for ${target} failed:`, e);
    } finally {
      setIsAIFetching(null);
    }
  };

  if (!track) return null;

  return (
    <div
      className={`fixed bottom-0 left-0 right-0 bg-background border-t shadow-2xl transition-all duration-500 z-50 flex flex-col ${
        isExpanded ? "h-[50vh]" : "h-20"
      }`}
    >
      <audio
        ref={audioRef}
        onTimeUpdate={() => setProgress(audioRef.current?.currentTime || 0)}
        onEnded={() => setIsPlaying(false)}
      />

      {/* 展開時ビュー */}
      {isExpanded && (
        <div className="flex-1 flex flex-col overflow-hidden animate-in slide-in-from-bottom duration-500">
          <div className="flex justify-end p-1 border-b bg-muted/5">
            <Button
              variant="ghost"
              size="icon"
              className="h-6 w-6"
              onClick={() => setIsExpanded(false)}
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
                        handleApplyChanges({ artwork_data: b64 });
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

                <Button
                  variant="outline"
                  size="sm"
                  className="rounded-full h-7 px-3 gap-1.5 text-[10px]"
                  onClick={() => handleAIFetch("artwork_info")}
                  disabled={!!isAIFetching}
                >
                  {isAIFetching === "artwork_info" ? (
                    <Loader2 className="h-3 w-3 animate-spin" />
                  ) : (
                    <Sparkles className="h-3 w-3" />
                  )}
                  AI検索
                </Button>

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
                        handleApplyChanges({ artwork_data: b64 });
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
                  <Button
                    variant="ghost"
                    size="sm"
                    className="h-7 text-[10px]"
                    onClick={() => handleAIFetch("lyrics")}
                    disabled={!!isAIFetching}
                  >
                    {isAIFetching === "lyrics" ? (
                      <Loader2 className="h-3 w-3 animate-spin mr-1" />
                    ) : (
                      <Sparkles className="h-3 w-3 mr-1" />
                    )}
                    AI Fetch
                  </Button>
                  <Button
                    size="sm"
                    className="h-7 text-[10px]"
                    onClick={() => handleApplyChanges({ lyrics: editedLyrics })}
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
              <Textarea
                value={editedLyrics}
                onChange={(e) => setEditedLyrics(e.target.value)}
                className="flex-1 font-serif text-sm leading-relaxed p-4 bg-muted/5 resize-none border-none focus-visible:ring-0"
                placeholder="歌詞を入力..."
              />
            </div>
          </div>
        </div>
      )}

      {/* ミニプレイヤーエリア (常に楽曲情報を表示) */}
      <div className="h-20 px-4 flex items-center justify-between bg-background/95 backdrop-blur shrink-0 z-10 relative">
        {/* Waveform Overlay */}
        <div 
          className="absolute top-0 left-0 right-0 h-full opacity-10 pointer-events-none z-0"
          style={{ maskImage: 'linear-gradient(to bottom, black, transparent)' }}
        >
           {/* Background waveform visual if needed, but we use the interactive one below */}
        </div>

        {/* Interactive Waveform / Progress Bar (Top Edge) */}
        <div 
          className="absolute -top-4 left-0 right-0 h-8 cursor-pointer group z-20 flex items-end"
          onClick={(e) => {
            const rect = e.currentTarget.getBoundingClientRect();
            const x = e.clientX - rect.left;
            const ratio = x / rect.width;
            if (audioRef.current) {
              audioRef.current.currentTime = ratio * audioRef.current.duration;
            }
          }}
        >
          <canvas
            ref={canvasRef}
            width={1000}
            height={32}
            className="w-full h-full block opacity-80 hover:opacity-100 transition-opacity"
          />
        </div>

        <div className="flex items-center gap-3 w-1/3 min-w-0 z-10">
          <div
            className="h-12 w-12 bg-muted rounded-md shrink-0 cursor-pointer overflow-hidden shadow-sm hover:ring-1 ring-primary transition-all flex items-center justify-center"
            onClick={() => setIsExpanded(true)}
          >
            {metadata?.artwork ? (
              <img
                src={`data:image/jpeg;base64,${metadata.artwork}`}
                className="h-full w-full object-cover"
              />
            ) : (
              <Music className="h-6 w-6 text-muted-foreground opacity-20" />
            )}
          </div>
          <div className="min-w-0">
            <div className="font-bold truncate text-sm tracking-tight leading-tight">
              {track.title}
            </div>
            <div className="flex items-center gap-2 mt-0.5">
              <span className="text-xs text-muted-foreground truncate">
                {track.artist}
                {track.year ? ` • ${track.year}` : ""}
              </span>
            </div>
          </div>
        </div>

        <div className="flex flex-col items-center gap-1 z-10">
          <div className="flex items-center gap-4">
            <Button
              variant="ghost"
              size="icon"
              className="h-8 w-8 text-muted-foreground"
            >
              <SkipBack className="h-4 w-4" />
            </Button>
            <Button
              size="icon"
              className="h-10 w-10 rounded-full shadow-md bg-primary text-primary-foreground hover:scale-105 transition-transform"
              onClick={() => {
                if (isPlaying) audioRef.current?.pause();
                else audioRef.current?.play();
                setIsPlaying(!isPlaying);
              }}
            >
              {isPlaying ? (
                <Pause className="h-5 w-5" />
              ) : (
                <Play className="h-5 w-5 ml-0.5" />
              )}
            </Button>
            <Button
              variant="ghost"
              size="icon"
              className="h-8 w-8 text-muted-foreground"
            >
              <SkipForward className="h-4 w-4" />
            </Button>
          </div>
          <div className="text-[10px] font-mono text-muted-foreground tabular-nums">
            {formatTime(progress)} /{" "}
            {formatTime(audioRef.current?.duration || track.duration)}
          </div>
        </div>

        <div className="flex items-center justify-end gap-4 w-1/3 z-10">
          <div className="flex items-center gap-2 w-24">
            <Volume2 className="h-3 w-3 text-muted-foreground shrink-0" />
            <Slider
              value={[volume * 100]}
              onValueChange={([v]) => {
                const newVol = v / 100;
                setVolume(newVol);
                if (audioRef.current) audioRef.current.volume = newVol;
              }}
              className="h-1.5"
            />
          </div>
          <Button
            variant="ghost"
            size="icon"
            className="h-8 w-8"
            onClick={() => setIsExpanded(!isExpanded)}
          >
            {isExpanded ? (
              <Minimize2 className="h-4 w-4 text-primary" />
            ) : (
              <Maximize2 className="h-4 w-4" />
            )}
          </Button>
          <Button
            variant="ghost"
            size="icon"
            onClick={onClose}
            className="h-8 w-8 hover:text-destructive transition-colors"
          >
            <X className="h-4 w-4" />
          </Button>
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
              handleApplyChanges({
                artwork_data: (ev.target?.result as string).split(",")[1],
              });
            reader.readAsDataURL(file);
          }
        }}
      />
    </div>
  );
}
