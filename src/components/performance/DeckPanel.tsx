import { useId, useState, type FormEvent } from "react";
import {
  CircleGauge,
  Disc3,
  FolderOpen,
  Link2,
  LockKeyhole,
  Pause,
  Play,
  RotateCcw,
  Square,
  Trash2,
  X,
} from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Slider } from "@/components/ui/slider";
import { cn } from "@/lib/utils";
import { usePerformanceMetadata } from "@/hooks/usePerformanceMetadata";
import type { DjEngineClient } from "@/services/dj-engine/client";
import type {
  ChannelState,
  DeckId,
  DeckState,
  EqBand,
  MetersPayload,
  TrackDescriptor,
} from "@/types/dj-engine";
import type { PerformanceTrackLoader } from "./types";
import { LevelMeter } from "./LevelMeter";

interface DeckPanelProps {
  deckId: DeckId;
  deck: DeckState;
  channel: ChannelState;
  meters: MetersPayload | null;
  connected: boolean;
  available: boolean;
  capabilities: readonly string[];
  busy: boolean;
  client: DjEngineClient;
  onRequestTrack?: PerformanceTrackLoader;
  runCommand: (task: () => Promise<unknown>) => Promise<void>;
}

const DECK_COLORS = {
  A: {
    accent: "text-cyan-300",
    border: "border-cyan-400/25",
    surface: "from-cyan-500/10",
    button: "border-cyan-400/40 bg-cyan-400/10 text-cyan-100 hover:bg-cyan-400/20",
  },
  B: {
    accent: "text-fuchsia-300",
    border: "border-fuchsia-400/25",
    surface: "from-fuchsia-500/10",
    button: "border-fuchsia-400/40 bg-fuchsia-400/10 text-fuchsia-100 hover:bg-fuchsia-400/20",
  },
  C: {
    accent: "text-cyan-300",
    border: "border-cyan-400/25",
    surface: "from-cyan-500/10",
    button: "border-cyan-400/40 bg-cyan-400/10 text-cyan-100 hover:bg-cyan-400/20",
  },
  D: {
    accent: "text-fuchsia-300",
    border: "border-fuchsia-400/25",
    surface: "from-fuchsia-500/10",
    button: "border-fuchsia-400/40 bg-fuchsia-400/10 text-fuchsia-100 hover:bg-fuchsia-400/20",
  },
} as const;

function formatTime(milliseconds: number): string {
  const totalSeconds = Math.max(0, Math.floor(milliseconds / 1000));
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return `${minutes}:${seconds.toString().padStart(2, "0")}`;
}

function readNumber(value: string): number | undefined {
  if (!value.trim()) return undefined;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : undefined;
}

export function DeckPanel({
  deckId,
  deck,
  channel,
  meters,
  connected,
  available,
  capabilities,
  busy,
  client,
  onRequestTrack,
  runCommand,
}: DeckPanelProps) {
  const id = useId();
  const colors = DECK_COLORS[deckId];
  const [showLoader, setShowLoader] = useState(false);
  const [trackId, setTrackId] = useState("");
  const [path, setPath] = useState("");
  const [title, setTitle] = useState("");
  const [artist, setArtist] = useState("");
  const [durationSeconds, setDurationSeconds] = useState("");
  const [bpm, setBpm] = useState("");
  const loaded = deck.track !== null;
  const disabled = !connected || busy || !available;
  const supports = (capability: string) => capabilities.includes(capability);
  const transportDisabled = disabled || !supports("deck.transport");
  const gainDisabled = disabled || !(supports("mixer.basic") || supports("mixer.gain"));
  const eqDisabled = disabled || !(supports("mixer.basic") || supports("mixer.eq"));
  const pflDisabled = disabled || !(supports("mixer.basic") || supports("mixer.pfl"));
  const duration = deck.track?.durationMs ?? 0;
  const meter = meters?.channels[deckId];
  const parsedTrackId = deck.track?.trackId && /^\d+$/.test(deck.track.trackId)
    ? Number(deck.track.trackId)
    : null;
  const { metadata, loading: metadataLoading, error: metadataError, replace: replaceMetadata } = usePerformanceMetadata(parsedTrackId);
  const metadataReady = parsedTrackId === null || (metadata !== null && !metadataLoading);

  const loadDescriptor = (descriptor: TrackDescriptor) =>
    runCommand(() => client.load(deckId, descriptor));

  const submitTrack = (event: FormEvent) => {
    event.preventDefault();
    const durationValue = readNumber(durationSeconds);
    if (!durationValue) return;
    const descriptor: TrackDescriptor = {
      trackId: trackId.trim(),
      path: path.trim(),
      durationMs: durationValue * 1000,
      title: title.trim() || undefined,
      artist: artist.trim() || undefined,
      bpm: readNumber(bpm),
    };
    void loadDescriptor(descriptor);
  };

  const requestTrack = () => {
    if (!onRequestTrack) {
      setShowLoader((current) => !current);
      return;
    }
    // Choosing a track may leave a modal open indefinitely; do not hold the
    // engine command lock (or disable Stop/transport) while awaiting the user.
    void Promise.resolve(onRequestTrack(deckId))
      .then((descriptor) => descriptor && runCommand(() => client.load(deckId, descriptor)))
      .catch((failure) => runCommand(() => Promise.reject(failure)));
  };

  const setEq = (band: EqBand, value: number[]) =>
    runCommand(() => client.setEq(deckId, band, value[0]));

  const makeLoop = () => {
    const beatMs = deck.effectiveBpm ? 60_000 / deck.effectiveBpm : 500;
    const startMs = deck.positionMs;
    const endMs = Math.min(duration, startMs + beatMs * 4);
    return runCommand(async () => {
      if (metadata) {
        await replaceMetadata({
          cue_points: metadata.cue_points,
          loops: [
            ...metadata.loops.filter((loop) => loop.id !== "quick-4-beat"),
            { id: "quick-4-beat", start_ms: startMs, end_ms: endMs, label: "4-beat quick loop" },
          ],
          beat_grid: metadata.beat_grid,
        });
      }
      await client.setLoop(deckId, startMs, endMs);
    });
  };

  const setOrJumpHotCue = (index: number, cue: number | null) => runCommand(async () => {
    if (cue !== null) {
      await client.jumpToHotCue(deckId, index);
      return;
    }
    if (metadata) {
      await replaceMetadata({
        cue_points: [
          ...metadata.cue_points.filter((item) => item.slot !== index),
          { slot: index, position_ms: deck.positionMs, label: "", color: null },
        ].sort((left, right) => left.slot - right.slot),
        loops: metadata.loops,
        beat_grid: metadata.beat_grid,
      });
    }
    await client.setHotCue(deckId, index, deck.positionMs);
  });

  const clearHotCue = (index: number) => runCommand(async () => {
    if (metadata) {
      await replaceMetadata({
        cue_points: metadata.cue_points.filter((item) => item.slot !== index),
        loops: metadata.loops,
        beat_grid: metadata.beat_grid,
      });
    }
    await client.clearHotCue(deckId, index);
  });

  return (
    <section
      aria-labelledby={`${id}-heading`}
      className={cn(
        "min-w-0 rounded-2xl border bg-gradient-to-b to-card p-4 shadow-xl shadow-black/10",
        colors.border,
        colors.surface
      )}
    >
      <div className="mb-4 flex items-start justify-between gap-3">
        <div className="flex min-w-0 items-center gap-3">
          <div className={cn("grid size-11 shrink-0 place-items-center rounded-full border bg-black/30", colors.border)}>
            <Disc3 className={cn("size-6", colors.accent, deck.status === "playing" && "animate-spin")} />
          </div>
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <h2 id={`${id}-heading`} className="text-lg font-bold tracking-tight">Deck {deckId}</h2>
              <Badge variant="outline" className="h-5 uppercase">{deck.status}</Badge>
            </div>
            <p className="truncate text-sm font-medium">{deck.track?.title ?? "No track loaded"}</p>
            <p className="truncate text-xs text-muted-foreground">{deck.track?.artist ?? "Load a descriptor to begin"}</p>
          </div>
        </div>
        <Button
          size="sm"
          variant="outline"
          className={colors.button}
          disabled={disabled || !supports("deck.load.async")}
          onClick={requestTrack}
        >
          <FolderOpen /> Load
        </Button>
      </div>

      {showLoader && !onRequestTrack && (
        <form onSubmit={submitTrack} className="mb-4 rounded-xl border border-border/70 bg-background/70 p-3">
          <div className="mb-3 flex items-center justify-between">
            <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">Track descriptor</p>
            <Button type="button" variant="ghost" size="icon" className="size-7" onClick={() => setShowLoader(false)} aria-label="Close track loader">
              <X />
            </Button>
          </div>
          <div className="grid gap-2 sm:grid-cols-2">
            <div><Label htmlFor={`${id}-track-id`}>Track ID</Label><Input id={`${id}-track-id`} required value={trackId} onChange={(e) => setTrackId(e.target.value)} placeholder="track-001" /></div>
            <div><Label htmlFor={`${id}-path`}>File path</Label><Input id={`${id}-path`} required value={path} onChange={(e) => setPath(e.target.value)} placeholder="/Music/track.wav" /></div>
            <div><Label htmlFor={`${id}-title`}>Title</Label><Input id={`${id}-title`} value={title} onChange={(e) => setTitle(e.target.value)} /></div>
            <div><Label htmlFor={`${id}-artist`}>Artist</Label><Input id={`${id}-artist`} value={artist} onChange={(e) => setArtist(e.target.value)} /></div>
            <div><Label htmlFor={`${id}-duration`}>Duration (seconds)</Label><Input id={`${id}-duration`} required min="0.001" step="0.001" type="number" value={durationSeconds} onChange={(e) => setDurationSeconds(e.target.value)} /></div>
            <div><Label htmlFor={`${id}-bpm`}>BPM (optional)</Label><Input id={`${id}-bpm`} min="20" max="300" step="0.01" type="number" value={bpm} onChange={(e) => setBpm(e.target.value)} /></div>
          </div>
          <Button type="submit" size="sm" className="mt-3 w-full" disabled={!trackId.trim() || !path.trim() || !durationSeconds}>Load into Deck {deckId}</Button>
        </form>
      )}

      <div className="rounded-xl border border-border/70 bg-black/20 p-3">
        <div className="mb-1 flex items-end justify-between font-mono">
          <span className={cn("text-2xl font-semibold tabular-nums", colors.accent)}>{formatTime(deck.positionMs)}</span>
          <span className="text-xs tabular-nums text-muted-foreground">-{formatTime(Math.max(0, duration - deck.positionMs))}</span>
        </div>
        <Slider
          aria-label={`Deck ${deckId} position`}
          min={0}
          max={Math.max(1, duration)}
          step={100}
          value={[Math.min(deck.positionMs, Math.max(1, duration))]}
          disabled={transportDisabled || !loaded}
          onValueCommit={(value) => void runCommand(() => client.seek(deckId, value[0], duration))}
        />
        <div className="mt-2 flex items-center justify-between text-[10px] uppercase tracking-wider text-muted-foreground">
          <span>{deck.effectiveBpm?.toFixed(1) ?? deck.track?.bpm?.toFixed(1) ?? "—"} BPM</span>
          <span>{deck.rate === 1 ? "±0.0" : `${deck.rate > 1 ? "+" : ""}${((deck.rate - 1) * 100).toFixed(1)}`}%</span>
          <span>{deck.track?.sampleRateHz ? `${deck.track.sampleRateHz / 1000} kHz` : "—"}</span>
        </div>
      </div>

      <div className="my-3 grid grid-cols-[1fr_auto_1fr] items-center gap-2">
        <Button variant="outline" size="sm" disabled={transportDisabled || !loaded} onClick={() => void runCommand(() => client.seek(deckId, 0, duration))}>
          <RotateCcw /> Cue
        </Button>
        <Button
          size="icon"
          className={cn("size-12 rounded-full", colors.button)}
          disabled={transportDisabled || !loaded}
          onClick={() => void runCommand(() => deck.status === "playing" ? client.pause(deckId) : client.play(deckId))}
          aria-label={`${deck.status === "playing" ? "Pause" : "Play"} deck ${deckId}`}
        >
          {deck.status === "playing" ? <Pause className="size-5" /> : <Play className="size-5 fill-current" />}
        </Button>
        <Button variant="outline" size="sm" disabled={transportDisabled || !loaded} onClick={() => void runCommand(() => client.unload(deckId))}>
          <Trash2 /> Eject
        </Button>
      </div>

      <div className="grid grid-cols-8 gap-1" aria-label={`Deck ${deckId} hot cues`}>
        {deck.hotCues.map((cue, index) => (
          <div key={index} className="relative">
            <Button
              variant="outline"
              size="sm"
              className={cn("w-full px-0 font-mono", cue !== null && colors.button)}
              disabled={disabled || !loaded || !supports("deck.hotcue") || !metadataReady}
              aria-label={`${cue === null ? "Set" : "Jump to"} hot cue ${index + 1}`}
              onClick={() => void setOrJumpHotCue(index, cue)}
            >
              {index + 1}
            </Button>
            {cue !== null && (
              <button
                type="button"
                className="absolute -right-1 -top-1 grid size-3.5 place-items-center rounded-full bg-destructive text-destructive-foreground"
                aria-label={`Clear hot cue ${index + 1}`}
                disabled={disabled || !supports("deck.hotcue") || !metadataReady}
                onClick={() => void clearHotCue(index)}
              ><X className="size-2.5" /></button>
            )}
          </div>
        ))}
      </div>

      <div className="mt-3 grid grid-cols-2 gap-2">
        <Button variant="outline" size="sm" disabled={disabled || !loaded || !supports("deck.loop") || !metadataReady || deck.positionMs >= duration} onClick={() => void makeLoop()}>
          <Square /> 4-beat loop
        </Button>
        <Button variant={deck.loopRegion?.enabled ? "secondary" : "outline"} size="sm" disabled={disabled || !supports("deck.loop") || !deck.loopRegion} onClick={() => void runCommand(() => client.enableLoop(deckId, !deck.loopRegion?.enabled))}>
          <Link2 /> {deck.loopRegion?.enabled ? "Loop on" : "Loop off"}
        </Button>
      </div>
      {metadata && metadata.loops.length > 0 && (
        <div className="mt-2 flex gap-2 overflow-x-auto pb-1" aria-label={`Deck ${deckId} saved loops`}>
          {metadata.loops.map((loop) => (
            <Button
              key={loop.id}
              variant="ghost"
              size="sm"
              className="shrink-0 text-xs"
              disabled={disabled || !loaded || !supports("deck.loop")}
              onClick={() => void runCommand(() => client.setLoop(deckId, loop.start_ms, loop.end_ms))}
            >
              {loop.label || loop.id}
            </Button>
          ))}
        </div>
      )}

      <div className="mt-4 grid grid-cols-2 gap-x-4 gap-y-3">
        <ControlSlider label="Tempo" value={deck.rate} min={0.25} max={4} step={0.01} display={`${((deck.rate - 1) * 100).toFixed(1)}%`} disabled={disabled || !loaded || !supports("deck.tempo")} onCommit={(value) => runCommand(() => client.setTempo(deckId, value))} />
        <ControlSlider label="Gain" value={channel.gain} min={0} max={1} step={0.01} display={`${Math.round(channel.gain * 100)}%`} disabled={gainDisabled} onCommit={(value) => runCommand(() => client.setChannelGain(deckId, value))} />
        <ControlSlider label="Low" value={channel.eqLow} min={0} max={4} step={0.05} display={`${channel.eqLow.toFixed(2)}×`} disabled={eqDisabled} onCommit={(value) => setEq("low", [value])} />
        <ControlSlider label="Mid" value={channel.eqMid} min={0} max={4} step={0.05} display={`${channel.eqMid.toFixed(2)}×`} disabled={eqDisabled} onCommit={(value) => setEq("mid", [value])} />
        <ControlSlider label="High" value={channel.eqHigh} min={0} max={4} step={0.05} display={`${channel.eqHigh.toFixed(2)}×`} disabled={eqDisabled} onCommit={(value) => setEq("high", [value])} />
        <div className="flex items-end gap-2">
          <Button variant={deck.keylock ? "secondary" : "outline"} size="sm" className="flex-1 px-2" disabled={disabled || !loaded || !supports("deck.keylock")} onClick={() => void runCommand(() => client.setKeylock(deckId, !deck.keylock))} aria-pressed={deck.keylock}><LockKeyhole /> Key</Button>
          <Button variant={deck.syncEnabled ? "secondary" : "outline"} size="sm" className="flex-1 px-2" disabled={disabled || !loaded || !capabilities.some((capability) => capability.startsWith("deck.sync"))} onClick={() => void runCommand(() => client.setSync(deckId, !deck.syncEnabled, deckId === "A" ? "B" : "A"))} aria-pressed={deck.syncEnabled}><CircleGauge /> Sync</Button>
        </div>
      </div>

      <div className="mt-4 flex items-center gap-3">
        <Button variant={channel.pfl ? "secondary" : "outline"} size="sm" disabled={pflDisabled} onClick={() => void runCommand(() => client.setPfl(deckId, !channel.pfl))} aria-pressed={channel.pfl}>PFL</Button>
        <div className="min-w-0 flex-1"><LevelMeter label={`Deck ${deckId}`} peak={meter?.peak} rms={meter?.rms} simulated={meters?.simulated} compact /></div>
      </div>

      {deck.lastError && <p className="mt-3 rounded-md bg-destructive/10 px-3 py-2 text-xs text-destructive">Deck error: {deck.lastError}</p>}
      {metadataError !== null && <p className="mt-3 rounded-md bg-destructive/10 px-3 py-2 text-xs text-destructive">Metadata error: {metadataError instanceof Error ? metadataError.message : String(metadataError)}</p>}
    </section>
  );
}

interface ControlSliderProps {
  label: string;
  value: number;
  min: number;
  max: number;
  step: number;
  display: string;
  disabled: boolean;
  onCommit: (value: number) => Promise<void>;
}

function ControlSlider({ label, value, min, max, step, display, disabled, onCommit }: ControlSliderProps) {
  return (
    <div className="space-y-1.5">
      <div className="flex items-center justify-between text-xs"><span className="text-muted-foreground">{label}</span><span className="font-mono tabular-nums">{display}</span></div>
      <Slider aria-label={label} value={[value]} min={min} max={max} step={step} disabled={disabled} onValueCommit={(next) => void onCommit(next[0])} />
    </div>
  );
}
