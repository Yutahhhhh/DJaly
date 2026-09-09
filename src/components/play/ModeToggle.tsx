import { BarChart3, Disc3, Headphones } from "lucide-react";
import { cn } from "@/lib/utils";

export type AppMode = "analysis" | "play" | "assist";

export const APP_MODES: readonly AppMode[] = ["analysis", "play", "assist"] as const;

export function isAppMode(value: unknown): value is AppMode {
  return typeof value === "string" && (APP_MODES as readonly string[]).includes(value);
}

const BUTTONS: { mode: AppMode; label: string; icon: typeof BarChart3; active: string }[] = [
  { mode: "analysis", label: "解析", icon: BarChart3, active: "bg-primary text-primary-foreground" },
  { mode: "play", label: "プレイ", icon: Disc3, active: "bg-cyan-500 text-slate-950" },
  { mode: "assist", label: "アシスト", icon: Headphones, active: "bg-amber-400 text-slate-950" },
];

export function ModeToggle({ mode, onChange, disabled = false }: { mode: AppMode; onChange: (mode: AppMode) => void; disabled?: boolean }) {
  return (
    <div className="flex gap-px rounded border border-slate-700 bg-slate-950 p-px" role="group" aria-label="Application mode">
      {BUTTONS.map(({ mode: value, label, icon: Icon, active }) => (
        <button key={value} disabled={disabled} type="button" onClick={() => onChange(value)} aria-pressed={mode === value}
          className={cn("flex h-6 items-center gap-1.5 rounded-sm px-2.5 text-[11px] font-semibold transition",
            mode === value ? active : "text-muted-foreground hover:bg-muted")}>
          <Icon className="size-3" />{label}
        </button>
      ))}
    </div>
  );
}
