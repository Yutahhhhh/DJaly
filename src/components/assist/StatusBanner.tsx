import { AlertTriangle, Info, ShieldAlert } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { assistService, type AssistSnapshot } from "@/services/assist";

type Tone = "info" | "warn" | "block";

const TONE_STYLES: Record<Tone, string> = {
  info: "border-slate-700 bg-slate-900/70 text-slate-300",
  warn: "border-amber-700/60 bg-amber-950/40 text-amber-200",
  block: "border-rose-800/60 bg-rose-950/40 text-rose-200",
};

const TONE_ICONS: Record<Tone, typeof Info> = {
  info: Info,
  warn: AlertTriangle,
  block: ShieldAlert,
};

function Banner({ tone, children }: { tone: Tone; children: React.ReactNode }) {
  const Icon = TONE_ICONS[tone];
  return (
    <div className={cn("flex gap-2 rounded border px-2.5 py-2 text-[11px] leading-relaxed", TONE_STYLES[tone])}>
      <Icon className="mt-px size-3.5 shrink-0" />
      <div className="min-w-0 flex-1 space-y-1.5">{children}</div>
    </div>
  );
}

/**
 * Explains, in the DJ's terms, why deck reading is not working right now.
 *
 * Every unavailable state gets its own sentence: nothing here degrades into a
 * blank list that looks like "there is nothing to play".
 */
export function StatusBanner({
  snapshot,
  libraryError,
  readError,
  windowMessage,
  onRefresh,
}: {
  snapshot: AssistSnapshot | null;
  libraryError: string | null;
  readError: string | null;
  windowMessage: string | null;
  onRefresh: () => void;
}) {
  const banners: React.ReactNode[] = [];

  if (snapshot && !snapshot.supported) {
    banners.push(
      <Banner key="unsupported" tone="info">
        <p>{snapshot.unavailable_reason}</p>
        <p className="text-slate-400">
          デスクトップアプリで rekordbox を起動し、デッキに曲を読み込んでください。
        </p>
      </Banner>,
    );
  } else if (snapshot && !snapshot.permission_granted) {
    banners.push(
      <Banner key="permission" tone="block">
        <p>
          macOS の「アクセシビリティ」権限がないため、rekordbox のデッキを読み取れません。
          
        </p>
        <div className="flex flex-wrap gap-1.5 pt-0.5">
          <Button size="sm" variant="secondary" className="h-6 px-2 text-[10px]"
            onClick={() => { void assistService.requestAccessibility().then(onRefresh).catch(onRefresh); }}>
            権限を許可する
          </Button>
          <Button size="sm" variant="ghost" className="h-6 px-2 text-[10px]"
            onClick={() => { void assistService.openAccessibilitySettings().catch(onRefresh); }}>
            システム設定を開く
          </Button>
          <Button size="sm" variant="ghost" className="h-6 px-2 text-[10px]" onClick={onRefresh}>
            再確認
          </Button>
        </div>
      </Banner>,
    );
  } else if (snapshot && !snapshot.app_running) {
    banners.push(
      <Banner key="not-running" tone="warn">
        <p>rekordbox が起動していません。起動して曲を読み込むと、ここにデッキが表示されます。</p>
      </Banner>,
    );
  } else if (snapshot?.unavailable_reason) {
    banners.push(
      <Banner key="unavailable" tone="warn">
        <p>{snapshot.unavailable_reason}</p>
      </Banner>,
    );
  }

  if (snapshot?.open_paths_error) {
    banners.push(
      <Banner key="open-files" tone="warn">
        <p>{snapshot.open_paths_error}</p>
      </Banner>,
    );
  }

  for (const warning of snapshot?.warnings ?? []) {
    banners.push(
      <Banner key={`warning-${warning}`} tone="warn">
        <p>{warning}</p>
      </Banner>,
    );
  }

  if (libraryError) {
    banners.push(
      <Banner key="library" tone="warn">
        <p>{libraryError}</p>
      </Banner>,
    );
  }

  if (readError) {
    banners.push(
      <Banner key="read" tone="warn">
        <p>デッキの読み取りに失敗しました: {readError}</p>
      </Banner>,
    );
  }

  if (windowMessage) {
    banners.push(
      <Banner key="window" tone="info">
        <p>{windowMessage}</p>
      </Banner>,
    );
  }

  if (!banners.length) return null;
  return <div className="space-y-1.5">{banners}</div>;
}
