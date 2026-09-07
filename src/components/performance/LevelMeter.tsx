import { cn } from "@/lib/utils";

interface LevelMeterProps {
  label: string;
  peak?: number;
  rms?: number;
  simulated?: boolean;
  compact?: boolean;
}

function percent(value: number | undefined): number {
  if (value === undefined || !Number.isFinite(value)) return 0;
  return Math.min(100, Math.max(0, value * 100));
}

export function LevelMeter({
  label,
  peak,
  rms,
  simulated = false,
  compact = false,
}: LevelMeterProps) {
  const peakValue = percent(peak);
  const rmsValue = percent(rms);

  return (
    <div className={cn("space-y-1", compact && "space-y-0.5")}>
      <div className="flex items-center justify-between text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
        <span>{label}</span>
        <span>{simulated ? "SIM" : `${Math.round(peakValue)}%`}</span>
      </div>
      <div
        className={cn(
          "relative overflow-hidden rounded-full bg-black/50 ring-1 ring-border/70",
          compact ? "h-1.5" : "h-2"
        )}
        role="meter"
        aria-label={`${label} peak level`}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={Math.round(peakValue)}
      >
        <div
          className="absolute inset-y-0 left-0 bg-emerald-500/50 transition-[width] duration-75"
          style={{ width: `${rmsValue}%` }}
        />
        <div
          className="absolute inset-y-0 left-0 bg-gradient-to-r from-emerald-400 via-amber-400 to-red-500 transition-[width] duration-75"
          style={{ width: `${peakValue}%`, clipPath: "inset(0 0 0 97%)" }}
        />
      </div>
    </div>
  );
}
