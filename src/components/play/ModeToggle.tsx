import { BarChart3, Disc3 } from "lucide-react";
import { cn } from "@/lib/utils";

export type AppMode = "analysis" | "play";

export function ModeToggle({ mode, onChange }: { mode: AppMode; onChange: (mode: AppMode) => void }) {
  return (
    <div className="flex gap-px rounded border border-slate-700 bg-slate-950 p-px" role="group" aria-label="Application mode">
      <button type="button" onClick={() => onChange("analysis")} aria-pressed={mode === "analysis"} className={cn("flex h-6 items-center gap-1.5 rounded-sm px-2.5 text-[11px] font-semibold transition", mode === "analysis" ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:bg-muted")}><BarChart3 className="size-3" />解析</button>
      <button type="button" onClick={() => onChange("play")} aria-pressed={mode === "play"} className={cn("flex h-6 items-center gap-1.5 rounded-sm px-2.5 text-[11px] font-semibold transition", mode === "play" ? "bg-cyan-500 text-slate-950" : "text-muted-foreground hover:bg-muted")}><Disc3 className="size-3" />プレイ</button>
    </div>
  );
}
