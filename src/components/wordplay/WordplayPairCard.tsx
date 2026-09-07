import {
  ArrowRight,
  Check,
  CircleCheck,
  Disc3,
  ExternalLink,
  Link2Off,
  Loader2,
  MapPin,
  Repeat2,
  Trash2,
} from "lucide-react";
import type { ReactNode } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { PlayButton } from "@/components/ui/PlayButton";
import { WordplayPair } from "@/services/wordplay";

const evidenceLabels = {
  hypothesis: "仮説",
  edit_listing: "エディット情報",
  performance: "プレイ実績",
} as const;

const approvalRequirement =
  "承認には、声ネタの開始・終了、次曲のイントロ開始・ワード着地、BPM差2%以内の設定が必要です。";

function formatTimestamp(seconds: number | null | undefined) {
  if (seconds === null || seconds === undefined) return null;
  const minutes = Math.floor(seconds / 60);
  const remainder = Math.floor(seconds % 60);
  return `${minutes}:${remainder.toString().padStart(2, "0")}`;
}

const cueModeLabels = {
  section_end: "展開末尾からカット",
  cue_drumming: "Cue打ち",
  cue_drumming_intro: "イントロ上でCue打ち",
} as const;

function PerformanceStep({
  number,
  label,
  description,
  phrase,
  timestamp,
  endTimestamp,
  track,
  trackId,
  icon,
}: {
  number: number;
  label: string;
  description: string;
  phrase?: string;
  timestamp?: number | null;
  endTimestamp?: number | null;
  track: WordplayPair["from_track"];
  trackId: number;
  icon: ReactNode;
}) {
  const startLabel = formatTimestamp(timestamp);
  const endLabel = formatTimestamp(endTimestamp);

  return (
    <div className="min-w-0 flex-1 rounded-lg border bg-muted/20 p-3">
      <div className="mb-2 flex items-center gap-2">
        <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-primary text-xs font-bold text-primary-foreground">
          {number}
        </span>
        <div className="min-w-0 flex-1">
          <p className="text-xs font-bold text-foreground">{label}</p>
          <p className="text-[10px] text-muted-foreground">{description}</p>
        </div>
        <span className="shrink-0 text-primary" aria-hidden="true">{icon}</span>
      </div>
      <div className="flex items-start gap-2 border-t pt-2">
        <div className="min-w-0 flex-1">
          {track ? (
            <>
              <p className="truncate text-xs font-semibold" title={track.title}>
                {track.title}
              </p>
              <p className="truncate text-[10px] text-muted-foreground">
                {track.artist}
              </p>
            </>
          ) : (
            <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
              <Link2Off className="h-3.5 w-3.5" />
              ライブラリから削除済み（ID: {trackId}）
            </div>
          )}
        </div>
        {track && (
          <PlayButton
            track={track}
            timestamp={timestamp}
            disabled={timestamp === null || timestamp === undefined}
            size="icon"
            variant="ghost"
            className="h-8 w-8 shrink-0"
            iconClassName="h-3.5 w-3.5"
            showPauseWhenPlaying
          />
        )}
      </div>
      <div className="mt-2 flex min-h-5 items-center gap-2 text-xs">
        {phrase && (
          <span className="min-w-0 flex-1 truncate font-medium italic text-foreground">
            “{phrase}”
          </span>
        )}
        <span className="ml-auto shrink-0 font-mono text-[10px] text-muted-foreground">
          {startLabel ? `${startLabel}${endLabel ? `–${endLabel}` : ""}` : "時刻未設定"}
        </span>
      </div>
    </div>
  );
}

interface WordplayPairCardProps {
  pair: WordplayPair;
  busy: boolean;
  disabled: boolean;
  onApprove: (pair: WordplayPair) => void;
  onToggleVerification: (pair: WordplayPair) => void;
  onRemove: (pair: WordplayPair) => void;
}

export function WordplayPairCard({
  pair,
  busy,
  disabled,
  onApprove,
  onToggleVerification,
  onRemove,
}: WordplayPairCardProps) {
  const requirementId = `wordplay-approval-requirement-${pair.id}`;
  const bpmDelta = pair.bpm_delta_percent;
  const landingTimestamp = pair.target_landing_timestamp ?? pair.to_timestamp;
  const cueMode = cueModeLabels[pair.source_cue_mode] ?? pair.source_cue_mode;

  return (
    <article className="rounded-xl border bg-card p-4 shadow-sm">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex flex-wrap items-center gap-2">
          <Badge variant={pair.status === "approved" ? "default" : "secondary"}>
            {pair.status === "approved" ? "承認済み" : "承認待ち"}
          </Badge>
          <Badge variant="outline">キーワード: {pair.keyword}</Badge>
          <Badge variant="outline">{evidenceLabels[pair.evidence_type]}</Badge>
          <Badge
            variant="outline"
            className={pair.verification_status === "tested" ? "border-green-500/50 text-green-600" : ""}
          >
            {pair.verification_status === "tested" ? "テスト済み" : "未検証"}
          </Badge>
          <Badge
            variant="outline"
            className={
              pair.boundary_fit
                ? "border-green-500/60 bg-green-500/10 text-green-700 dark:text-green-400"
                : "border-destructive/50 bg-destructive/5 text-destructive"
            }
          >
            {pair.boundary_fit ? "プレイ構成OK" : "位置設定が不足"}
          </Badge>
          <Badge variant="outline">
            BPM差 {bpmDelta === null ? "未計算" : `${bpmDelta.toFixed(2)}%`}
          </Badge>
          {pair.style_fit !== undefined && (
            <Badge
              variant="outline"
              className={
                pair.style_fit
                  ? "border-green-500/60 bg-green-500/10 text-green-700 dark:text-green-400"
                  : "border-amber-500/60 bg-amber-500/10 text-amber-700 dark:text-amber-400"
              }
            >
              {pair.style_fit ? "曲調OK" : "曲調差あり"}
            </Badge>
          )}
        </div>
        <div className="flex items-center gap-2">
          <Button
            size="sm"
            variant="outline"
            onClick={() => onToggleVerification(pair)}
            disabled={disabled}
            aria-label={`${pair.keyword} のワードプレイを${pair.verification_status === "tested" ? "未検証に戻す" : "テスト済みにする"}`}
            title="実際に音源を確認した結果を記録します"
          >
            {busy ? (
              <Loader2 className="mr-1 h-4 w-4 animate-spin" />
            ) : (
              <CircleCheck className="mr-1 h-4 w-4" />
            )}
            {pair.verification_status === "tested" ? "未検証に戻す" : "テスト済みにする"}
          </Button>
          {pair.status === "pending" && (
            <Button
              size="sm"
              onClick={() => onApprove(pair)}
              disabled={disabled || !pair.boundary_fit || !pair.from_track || !pair.to_track}
              aria-label={`${pair.keyword} のワードプレイを承認。${approvalRequirement}`}
              aria-describedby={!pair.boundary_fit ? requirementId : undefined}
              title={!pair.boundary_fit ? approvalRequirement : "ワードプレイを承認"}
            >
              {busy ? <Loader2 className="mr-1 h-4 w-4 animate-spin" /> : <Check className="mr-1 h-4 w-4" />}
              承認
            </Button>
          )}
          <Button
            size="sm"
            variant={pair.status === "pending" ? "outline" : "destructive"}
            onClick={() => onRemove(pair)}
            disabled={disabled}
            aria-label={`${pair.keyword} のワードプレイを${pair.status === "pending" ? "却下" : "削除"}`}
          >
            {busy ? <Loader2 className="mr-1 h-4 w-4 animate-spin" /> : <Trash2 className="mr-1 h-4 w-4" />}
            {pair.status === "pending" ? "却下（削除）" : "削除"}
          </Button>
        </div>
      </div>

      {!pair.boundary_fit && (
        <p id={requirementId} className="mt-3 text-xs text-destructive">
          {approvalRequirement}
        </p>
      )}

      <div className="my-4">
        <p className="mb-2 text-xs font-semibold text-muted-foreground">プレイ順</p>
        <div className="flex flex-col items-stretch gap-2 md:flex-row md:items-center">
          <PerformanceStep
            number={1}
            label="Cue打ちする声ネタ"
            description="特徴的な声をタップ／リピート"
            phrase={pair.source_phrase || pair.keyword}
            timestamp={pair.from_timestamp}
            endTimestamp={pair.source_cue_end_timestamp}
            track={pair.from_track}
            trackId={pair.from_track_id}
            icon={<Repeat2 className="h-4 w-4" />}
          />
          <ArrowRight className="h-4 w-4 shrink-0 self-center rotate-90 text-muted-foreground md:rotate-0" aria-hidden="true" />
          <PerformanceStep
            number={2}
            label="次曲イントロ開始"
            description="声ネタを打ちながら次曲を走らせる"
            timestamp={pair.target_intro_timestamp}
            track={pair.to_track}
            trackId={pair.to_track_id}
            icon={<Disc3 className="h-4 w-4" />}
          />
          <ArrowRight className="h-4 w-4 shrink-0 self-center rotate-90 text-muted-foreground md:rotate-0" aria-hidden="true" />
          <PerformanceStep
            number={3}
            label="ワード着地"
            description="狙った冒頭／展開のワードへつなぐ"
            phrase={pair.target_phrase || pair.keyword}
            timestamp={landingTimestamp}
            track={pair.to_track}
            trackId={pair.to_track_id}
            icon={<MapPin className="h-4 w-4" />}
          />
        </div>
        {cueMode && (
          <p className="mt-2 text-[10px] text-muted-foreground">
            プレイ方法: {cueMode}
          </p>
        )}
      </div>

      {(pair.transition_notes || pair.source_url) && (
        <div className="flex flex-wrap items-start justify-between gap-3 border-t pt-3 text-xs text-muted-foreground">
          <p className="min-w-0 flex-1 whitespace-pre-wrap">
            {pair.transition_notes || "補足なし"}
          </p>
          {pair.source_url && (
            <a
              href={pair.source_url}
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center gap-1 text-primary hover:underline"
            >
              根拠を開く <ExternalLink className="h-3 w-3" />
            </a>
          )}
        </div>
      )}
    </article>
  );
}
