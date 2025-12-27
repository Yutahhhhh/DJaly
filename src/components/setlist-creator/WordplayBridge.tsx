import React, { useState } from "react";
import { MessageSquareQuote, Play, Square, ExternalLink, X } from "lucide-react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { useAudioPreview } from "@/hooks/useAudioPreview";

interface WordplayData {
  keyword: string;
  source_phrase: string;
  target_phrase: string;
  from_track_id: number;
  from_timestamp?: number;
  to_timestamp?: number;
}

interface WordplayBridgeProps {
  data: string;
  fromTrackPath?: string;
  toTrackPath?: string;
  onDelete?: () => void;
}

export function WordplayBridge({
  data,
  fromTrackPath,
  toTrackPath,
  onDelete,
}: WordplayBridgeProps) {
  const [isPlaying, setIsPlaying] = useState<"from" | "to" | null>(null);

  // カスタムフックを使用してプレビュー再生を管理
  const { playPreview, stopPreview } = useAudioPreview({
    maxDuration: 10000, // 10秒
    preRollTime: 1, // 指定位置の1秒前から再生
    onPlayStart: () => {}, // setIsPlayingは個別に管理
    onPlayEnd: () => setIsPlaying(null),
    onError: (error) => {
      console.error("プレビュー再生エラー:", error);
      setIsPlaying(null);
    },
  });

  const wordplay: WordplayData | null = React.useMemo(() => {
    try {
      return JSON.parse(data);
    } catch (e) {
      console.error("ワードプレイJSONのパースに失敗しました", e);
      return null;
    }
  }, [data]);

  if (!wordplay) return null;

  /**
   * 指定された箇所のプレビュー再生を開始
   */
  const handlePlayPhrase = (
    path: string | undefined,
    timestamp: number | undefined,
    type: "from" | "to"
  ) => {
    if (!path) return;

    setIsPlaying(type);
    playPreview(path, timestamp);
  };

  /**
   * プレビュー再生を停止
   */
  const handleStopPhrase = () => {
    stopPreview();
    setIsPlaying(null);
  };

  return (
    <div className="relative flex flex-col items-center z-10 px-12 group/bridge py-4">
      {/* 接続ライン */}
      <div className="h-6 w-0.5 bg-primary/20 group-hover/bridge:bg-primary/40 transition-colors" />

      {/* ワードプレイ情報カード */}
      <div className="bg-background border-2 border-primary/20 rounded-xl p-3 shadow-lg w-full max-w-md transition-all group-hover/bridge:border-primary/40">
        <div className="flex items-center gap-2 mb-3 pb-2 border-b border-dashed border-border">
          <MessageSquareQuote className="h-4 w-4 text-primary" />
          <span className="text-[10px] font-black uppercase tracking-tighter text-muted-foreground flex-1">
            Lyrical Bridge via{" "}
            <span className="text-primary font-bold">{wordplay.keyword}</span>
          </span>
          {onDelete && (
            <Button
              variant="ghost"
              size="icon"
              className="h-5 w-5 hover:bg-destructive/10 hover:text-destructive transition-colors rounded-full"
              onClick={onDelete}
              title="ワードプレイを削除"
            >
              <X className="h-3 w-3" />
            </Button>
          )}
        </div>

        <div className="grid grid-cols-1 gap-3 text-xs">
          {/* 接続元 (Exit Phrase) */}
          <div className="flex items-center gap-2">
            <div className="flex-1 bg-muted/50 p-2.5 rounded italic text-muted-foreground relative min-w-0 border border-transparent">
              <div className="truncate pr-6 text-[11px]">
                "{wordplay.source_phrase || wordplay.keyword}"
              </div>
              <div className="absolute right-1 bottom-0.5 text-[7px] opacity-40 font-bold uppercase">
                Exit
              </div>
            </div>
            {fromTrackPath && (
              <Button
                size="icon"
                variant="ghost"
                className={cn(
                  "h-8 w-8 shrink-0 rounded-full transition-all shadow-sm",
                  isPlaying === "from"
                    ? "bg-primary text-primary-foreground hover:bg-primary/90"
                    : "hover:bg-primary/10 text-primary border border-primary/10"
                )}
                onClick={() =>
                  isPlaying === "from"
                    ? handleStopPhrase()
                    : handlePlayPhrase(fromTrackPath, wordplay.from_timestamp, "from")
                }
              >
                {isPlaying === "from" ? (
                  <Square className="h-3 w-3 fill-current" />
                ) : (
                  <Play className="h-3 w-3 fill-current ml-0.5" />
                )}
              </Button>
            )}
          </div>

          {/* 遷移アイコン */}
          <div className="flex justify-center -my-2 opacity-30">
            <ExternalLink className="h-3 w-3 text-primary" />
          </div>

          {/* 接続先 (Entry Phrase) */}
          <div className="flex items-center gap-2">
            <div className="flex-1 bg-primary/5 p-2.5 rounded italic font-medium text-foreground relative border border-primary/10 min-w-0">
              <div className="truncate pr-6 text-[11px]">
                "{wordplay.target_phrase}"
              </div>
              <div className="absolute right-1 bottom-0.5 text-[7px] text-primary/40 font-bold uppercase">
                Entry
              </div>
            </div>
            {toTrackPath && (
              <Button
                size="icon"
                variant="ghost"
                className={cn(
                  "h-8 w-8 shrink-0 rounded-full transition-all shadow-sm",
                  isPlaying === "to"
                    ? "bg-primary text-primary-foreground hover:bg-primary/90"
                    : "hover:bg-primary/10 text-primary border border-primary/10"
                )}
                onClick={() =>
                  isPlaying === "to"
                    ? handleStopPhrase()
                    : handlePlayPhrase(toTrackPath, wordplay.to_timestamp, "to")
                }
              >
                {isPlaying === "to" ? (
                  <Square className="h-3 w-3 fill-current" />
                ) : (
                  <Play className="h-3 w-3 fill-current ml-0.5" />
                )}
              </Button>
            )}
          </div>
        </div>
      </div>

      <div className="h-6 w-0.5 bg-primary/20 group-hover/bridge:bg-primary/40 transition-colors" />
    </div>
  );
}
