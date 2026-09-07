import React, { useState } from "react";
import type { ReactNode } from "react";
import { Disc3, MapPin, Play, Repeat2, Square, X } from "lucide-react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { useAudioPreview } from "@/hooks/useAudioPreview";

interface WordplayData {
  keyword: string;
  source_phrase: string;
  target_phrase: string;
  from_track_id: number;
  from_timestamp?: number | null;
  to_timestamp?: number | null;
  source_cue_end_timestamp?: number | null;
  target_intro_timestamp?: number | null;
  target_landing_timestamp?: number | null;
  source_cue_mode?: "section_end" | "cue_drumming" | "cue_drumming_intro";
}

interface WordplayBridgeProps {
  data: string;
  fromTrackPath?: string;
  toTrackPath?: string;
  onDelete?: () => void;
}

function formatTimestamp(seconds: number | null | undefined) {
  if (seconds === null || seconds === undefined) return "時刻未設定";
  const minutes = Math.floor(seconds / 60);
  const remainder = Math.floor(seconds % 60);
  return `${minutes}:${remainder.toString().padStart(2, "0")}`;
}

const cueModeLabels = {
  section_end: "展開末尾からカット",
  cue_drumming: "Cue打ち",
  cue_drumming_intro: "イントロ上でCue打ち",
} as const;

function BridgeStep({
  number,
  label,
  detail,
  timestamp,
  endTimestamp,
  icon,
  canPlay,
  playing,
  onPlay,
  onStop,
}: {
  number: number;
  label: string;
  detail: string;
  timestamp?: number | null;
  endTimestamp?: number | null;
  icon: ReactNode;
  canPlay: boolean;
  playing: boolean;
  onPlay: () => void;
  onStop: () => void;
}) {
  const endLabel = endTimestamp === null || endTimestamp === undefined
    ? null
    : formatTimestamp(endTimestamp);

  return (
    <div className="relative flex items-center gap-2 rounded-lg border bg-muted/25 p-2.5">
      <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-primary text-[10px] font-bold text-primary-foreground">
        {number}
      </span>
      <span className="shrink-0 text-primary" aria-hidden="true">{icon}</span>
      <div className="min-w-0 flex-1">
        <p className="text-[11px] font-bold text-foreground">{label}</p>
        <p className="truncate text-[10px] text-muted-foreground" title={detail}>{detail}</p>
      </div>
      <span className="shrink-0 font-mono text-[9px] text-muted-foreground">
        {formatTimestamp(timestamp)}{endLabel ? `–${endLabel}` : ""}
      </span>
      <Button
        size="icon"
        variant="ghost"
        className={cn(
          "h-7 w-7 shrink-0 rounded-full border border-primary/10 text-primary",
          playing && "bg-primary text-primary-foreground hover:bg-primary/90"
        )}
        disabled={!canPlay}
        onClick={playing ? onStop : onPlay}
        aria-label={playing ? `${label}のプレビューを停止` : `${label}をプレビュー`}
      >
        {playing ? (
          <Square className="h-3 w-3 fill-current" />
        ) : (
          <Play className="ml-0.5 h-3 w-3 fill-current" />
        )}
      </Button>
    </div>
  );
}

export function WordplayBridge({
  data,
  fromTrackPath,
  toTrackPath,
  onDelete,
}: WordplayBridgeProps) {
  const [isPlaying, setIsPlaying] = useState<"cue" | "intro" | "landing" | null>(null);

  const wordplay: WordplayData | null = React.useMemo(() => {
    try {
      return JSON.parse(data);
    } catch (e) {
      console.error("ワードプレイJSONのパースに失敗しました", e);
      return null;
    }
  }, [data]);

  const landingTimestamp = wordplay?.target_landing_timestamp ?? wordplay?.to_timestamp;
  const introTimestamp = wordplay?.target_intro_timestamp;
  const cueMeta = wordplay?.source_cue_mode
    ? cueModeLabels[wordplay.source_cue_mode]
    : null;
  const targetRunSeconds =
    introTimestamp !== null && introTimestamp !== undefined &&
    landingTimestamp !== null && landingTimestamp !== undefined
      ? Math.max(0, landingTimestamp - introTimestamp) + 3
      : 0;

  // カスタムフックを使用してプレビュー再生を管理
  const { playPreview, stopPreview } = useAudioPreview({
    // イントロから着地語までを続けて確認できる長さを確保する。
    maxDuration: Math.max(10000, targetRunSeconds * 1000),
    preRollTime: 1, // 指定位置の1秒前から再生
    onPlayStart: () => {}, // setIsPlayingは個別に管理
    onPlayEnd: () => setIsPlaying(null),
    onError: (error) => {
      console.error("プレビュー再生エラー:", error);
      setIsPlaying(null);
    },
  });

  if (!wordplay) return null;

  /**
   * 指定された箇所のプレビュー再生を開始
   */
  const handlePlayPhrase = (
    path: string | undefined,
    timestamp: number | null | undefined,
    type: "cue" | "intro" | "landing"
  ) => {
    if (!path) return;

    setIsPlaying(type);
    playPreview(path, timestamp ?? undefined);
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
        <div className="mb-3 flex items-center gap-2 border-b border-dashed border-border pb-2">
          <Repeat2 className="h-4 w-4 text-primary" />
          <span className="flex-1 text-[10px] font-black tracking-tight text-muted-foreground">
            Cueワードプレイ: <span className="font-bold text-primary">{wordplay.keyword}</span>
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

        <div className="grid grid-cols-1 gap-2 text-xs">
          <BridgeStep
            number={1}
            label="Cue打ちする声ネタ"
            detail={`“${wordplay.source_phrase || wordplay.keyword}” をタップ／リピート${cueMeta ? `（${cueMeta}）` : ""}`}
            timestamp={wordplay.from_timestamp}
            endTimestamp={wordplay.source_cue_end_timestamp}
            icon={<Repeat2 className="h-3.5 w-3.5" />}
            canPlay={Boolean(fromTrackPath)}
            playing={isPlaying === "cue"}
            onPlay={() => handlePlayPhrase(fromTrackPath, wordplay.from_timestamp, "cue")}
            onStop={handleStopPhrase}
          />
          <BridgeStep
            number={2}
            label="次曲イントロ開始"
            detail="声ネタを打ちながら次曲を走らせる"
            timestamp={introTimestamp}
            icon={<Disc3 className="h-3.5 w-3.5" />}
            canPlay={Boolean(toTrackPath && introTimestamp !== null && introTimestamp !== undefined)}
            playing={isPlaying === "intro"}
            onPlay={() => handlePlayPhrase(toTrackPath, introTimestamp, "intro")}
            onStop={handleStopPhrase}
          />
          <BridgeStep
            number={3}
            label="ワード着地"
            detail={`“${wordplay.target_phrase || wordplay.keyword}”`}
            timestamp={landingTimestamp}
            icon={<MapPin className="h-3.5 w-3.5" />}
            canPlay={Boolean(toTrackPath && landingTimestamp !== null && landingTimestamp !== undefined)}
            playing={isPlaying === "landing"}
            onPlay={() => handlePlayPhrase(toTrackPath, landingTimestamp, "landing")}
            onStop={handleStopPhrase}
          />
        </div>
      </div>

      <div className="h-6 w-0.5 bg-primary/20 group-hover/bridge:bg-primary/40 transition-colors" />
    </div>
  );
}
