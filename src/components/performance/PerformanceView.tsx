import { useCallback, useEffect, useRef, useState } from "react";
import {
  AlertTriangle,
  Cable,
  CircleStop,
  Gauge,
  Loader2,
  Power,
  Radio,
  RefreshCw,
  Unplug,
} from "lucide-react";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Slider } from "@/components/ui/slider";
import { Input } from "@/components/ui/input";
import { useDjEngine } from "@/hooks/useDjEngine";
import { cn } from "@/lib/utils";
import type { DeckId } from "@/types/dj-engine";
import type { TrackDescriptor } from "@/types/dj-engine";
import type { Track } from "@/types";
import { performanceMetadataService } from "@/services/performance-metadata";
import { DeckPanel } from "./DeckPanel";
import { LibraryTrackPicker } from "./LibraryTrackPicker";
import { LevelMeter } from "./LevelMeter";
import type { PerformanceViewProps } from "./types";

export function PerformanceView({ onRequestTrack }: PerformanceViewProps) {
  const { status, state, error, busy, client, start, stop, connect, refreshStatus } = useDjEngine();
  const [commandError, setCommandError] = useState<string | null>(null);
  const [commandBusy, setCommandBusy] = useState(false);
  const [pickerDeck, setPickerDeck] = useState<DeckId | null>(null);
  const [hydrationAttempt, setHydrationAttempt] = useState(0);
  const [outputDevice, setOutputDevice] = useState(() => localStorage.getItem("djaly.djOutputDevice") ?? "");
  const pickerResolver = useRef<((track: TrackDescriptor | null) => void) | null>(null);
  const pendingHotCues = useRef<Partial<Record<DeckId, { trackId: string; cues: { slot: number; positionMs: number }[] }>>>({});
  const hydratingHotCues = useRef(new Set<DeckId>());
  const snapshot = state.snapshot;
  // The status returned by start can predate connect; the client session is the
  // authoritative connection signal once a snapshot has arrived.
  const connected = Boolean(
    snapshot &&
    status?.running &&
    client.getSessionId() &&
    !state.sessionInvalidated &&
    state.droppedEvents === 0
  );
  const blocked = busy || commandBusy;

  const runCommand = useCallback(async (task: () => Promise<unknown>) => {
    setCommandBusy(true);
    setCommandError(null);
    try {
      await task();
    } catch (commandFailure) {
      setCommandError(commandFailure instanceof Error ? commandFailure.message : String(commandFailure));
    } finally {
      setCommandBusy(false);
    }
  }, []);

  const lifecycle = async (task: () => Promise<unknown>) => {
    setCommandError(null);
    await task();
  };

  const requestLibraryTrack = useCallback((deck: DeckId) => {
    if (pickerResolver.current) pickerResolver.current(null);
    setPickerDeck(deck);
    return new Promise<TrackDescriptor | null>((resolve) => {
      pickerResolver.current = resolve;
    });
  }, []);

  const closePicker = useCallback(() => {
    pickerResolver.current?.(null);
    pickerResolver.current = null;
    setPickerDeck(null);
  }, []);

  const selectTrack = useCallback(async (track: Track) => {
    const targetDeck = pickerDeck;
    let bpm = track.bpm || undefined;
    let beatgridOffsetMs: number | undefined;
    if (targetDeck) {
      try {
        const metadata = await performanceMetadataService.get(track.id);
        bpm = metadata.beat_grid?.bpm ?? bpm;
        beatgridOffsetMs = metadata.beat_grid?.first_beat_ms;
        pendingHotCues.current[targetDeck] = {
          trackId: String(track.id),
          cues: metadata.cue_points.map((cue) => ({ slot: cue.slot, positionMs: cue.position_ms })),
        };
      } catch (failure) {
        setCommandError(`保存済みCue/Gridの取得に失敗しました: ${failure instanceof Error ? failure.message : String(failure)}`);
      }
    }
    pickerResolver.current?.({
      trackId: String(track.id),
      path: track.filepath,
      durationMs: track.duration * 1000,
      title: track.title || undefined,
      artist: track.artist || undefined,
      bpm,
      beatgridOffsetMs,
    });
    pickerResolver.current = null;
    setPickerDeck(null);
  }, [pickerDeck]);

  useEffect(() => {
    if (!snapshot?.engine.capabilities.includes("deck.hotcue")) return;
    for (const deckId of ["A", "B"] as DeckId[]) {
      const pending = pendingHotCues.current[deckId];
      const deck = snapshot.decks[deckId];
      if (!pending || hydratingHotCues.current.has(deckId) || deck.status !== "ready" || deck.track?.trackId !== pending.trackId) continue;
      hydratingHotCues.current.add(deckId);
      let applied = false;
      void runCommand(async () => {
        for (const cue of pending.cues) await client.setHotCue(deckId, cue.slot, cue.positionMs);
        applied = true;
      }).finally(() => {
        hydratingHotCues.current.delete(deckId);
        if (applied) {
          delete pendingHotCues.current[deckId];
          setHydrationAttempt(0);
        } else {
          const delayMs = Math.min(1_000 * 2 ** Math.min(hydrationAttempt, 3), 10_000);
          setTimeout(() => setHydrationAttempt((attempt) => attempt + 1), delayMs);
        }
      });
    }
  }, [client, hydrationAttempt, runCommand, snapshot]);

  const trackLoader = onRequestTrack ?? requestLibraryTrack;
  const realHostSelected = Boolean(status?.binaryPath && /mixxx-engine-host|DJalyMixxxHost/.test(status.binaryPath));

  return (
    <main className="h-full overflow-y-auto bg-gradient-to-b from-background via-background to-muted/20 p-4 lg:p-6">
      <div className="mx-auto max-w-[1600px] space-y-4">
        <header className="flex flex-col gap-4 rounded-2xl border bg-card/80 p-4 shadow-sm backdrop-blur lg:flex-row lg:items-center lg:justify-between">
          <div>
            <div className="flex items-center gap-2">
              <Radio className="size-5 text-primary" />
              <h1 className="text-2xl font-bold tracking-tight">Performance</h1>
              <Badge variant={status?.simulated ? "secondary" : "default"} className="uppercase">
                {status === null
                  ? "Checking host"
                  : status.simulated
                    ? "Simulator · no audio"
                    : snapshot?.engine.audioAvailable
                      ? "Real audio host"
                      : "Real host · audio unavailable"}
              </Badge>
            </div>
            <p className="mt-1 text-sm text-muted-foreground">Two-deck control surface for the native DJ engine</p>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <StatusPill label="Installed" active={Boolean(status?.installed)} pending={status === null} />
            <StatusPill label="Running" active={Boolean(status?.running)} pending={status === null} />
            <StatusPill label="Connected" active={connected} pending={status === null} />
            <Button size="sm" variant="outline" disabled={blocked} onClick={() => void refreshStatus()} aria-label="Refresh engine status"><RefreshCw className={cn(blocked && "animate-spin")} /></Button>
            {!status?.running && realHostSelected && (
              <Input
                aria-label="Core Audio output device name"
                className="h-9 w-52"
                placeholder="Exact Core Audio device name"
                value={outputDevice}
                onChange={(event) => {
                  setOutputDevice(event.target.value);
                  localStorage.setItem("djaly.djOutputDevice", event.target.value);
                }}
              />
            )}
            {!status?.running ? (
              <Button size="sm" disabled={blocked || status === null || !status.installed || (realHostSelected && !outputDevice.trim())} onClick={() => void lifecycle(() => start(outputDevice))}>
                {busy ? <Loader2 className="animate-spin" /> : <Power />} Start engine
              </Button>
            ) : !connected ? (
              <Button size="sm" disabled={blocked} onClick={() => void lifecycle(connect)}><Cable /> Connect</Button>
            ) : (
              <Button size="sm" variant="destructive" disabled={busy} onClick={() => void lifecycle(stop)}><CircleStop /> Stop</Button>
            )}
          </div>
        </header>

        {(!status?.installed || status.detail || snapshot?.audio.applied === false) && status !== null && (
          <Alert variant={status.installed ? "default" : "destructive"}>
            {status.installed ? <Unplug className="size-4" /> : <AlertTriangle className="size-4" />}
            <AlertTitle>{status.installed ? "Engine host information" : "DJ engine is not installed"}</AlertTitle>
            <AlertDescription>{status.detail ?? snapshot?.audio.reason ?? (status.simulated ? "The simulator is connected; it never produces audio." : "Install or configure the native DJ engine host to use audio output.")}</AlertDescription>
          </Alert>
        )}

        {(error || commandError || status?.lastError) && (
          <Alert variant="destructive">
            <AlertTriangle className="size-4" />
            <AlertTitle>Engine error</AlertTitle>
            <AlertDescription>{commandError ?? error ?? status?.lastError}</AlertDescription>
          </Alert>
        )}

        {snapshot ? (
          <>
            <div className="grid gap-4 xl:grid-cols-2">
              {(["A", "B"] as DeckId[]).map((deckId) => (
                <DeckPanel
                  key={deckId}
                  deckId={deckId}
                  deck={snapshot.decks[deckId]}
                  channel={snapshot.mixer.channels[deckId]}
                  meters={state.meters}
                  connected={connected}
                  available={snapshot.engine.decks.includes(deckId)}
                  capabilities={snapshot.engine.capabilities}
                  busy={blocked}
                  client={client}
                  onRequestTrack={trackLoader}
                  runCommand={runCommand}
                />
              ))}
            </div>

            <section aria-label="Master mixer" className="rounded-2xl border bg-card p-4 shadow-lg">
              <div className="grid items-center gap-5 lg:grid-cols-[1fr_2fr_1fr]">
                <div>
                  <div className="mb-1 flex items-center gap-2"><Gauge className="size-4 text-primary" /><h2 className="font-semibold">Master</h2></div>
                  <LevelMeter label="Output" peak={state.meters?.master.peak} rms={state.meters?.master.rms} simulated={state.meters?.simulated} />
                  <Button
                    variant="outline"
                    size="sm"
                    className="mt-2 w-full"
                    disabled={blocked || !connected || !snapshot.engine.capabilities.some((capability) => capability.startsWith("meters."))}
                    onClick={() => void runCommand(() => client.subscribeMeters(!snapshot.meters.enabled, 50))}
                    aria-pressed={snapshot.meters.enabled}
                  >
                    {snapshot.meters.enabled ? "Disable meters" : "Enable meters"}
                  </Button>
                </div>
                <div className="space-y-2">
                  <div className="flex items-center justify-between text-xs font-medium"><span className="text-cyan-300">DECK A</span><span className="font-mono tabular-nums">Crossfader {snapshot.mixer.crossfader.toFixed(2)}</span><span className="text-fuchsia-300">DECK B</span></div>
                  <Slider aria-label="Crossfader" min={-1} max={1} step={0.01} value={[snapshot.mixer.crossfader]} disabled={blocked || !connected || !snapshot.engine.capabilities.some((capability) => capability === "mixer.basic" || capability === "mixer.crossfader")} onValueCommit={(value) => void runCommand(() => client.setCrossfader(value[0]))} />
                  <div className="flex justify-between text-[10px] uppercase tracking-wider text-muted-foreground"><span>A</span><span>Center</span><span>B</span></div>
                </div>
                <div className="space-y-2">
                  <div className="flex items-center justify-between text-xs"><span className="text-muted-foreground">Master gain</span><span className="font-mono tabular-nums">{Math.round(snapshot.mixer.masterGain * 100)}%</span></div>
                  <Slider aria-label="Master gain" min={0} max={1} step={0.01} value={[snapshot.mixer.masterGain]} disabled={blocked || !connected || !snapshot.engine.capabilities.some((capability) => capability === "mixer.basic" || capability === "mixer.gain")} onValueCommit={(value) => void runCommand(() => client.setMasterGain(value[0]))} />
                  <p className="text-[10px] text-muted-foreground">Audio: {snapshot.audio.sampleRateHz / 1000} kHz · {snapshot.audio.bufferFrames} frames · {snapshot.audio.applied ? "device applied" : "not applied"}</p>
                </div>
              </div>
            </section>

            <footer className="flex flex-wrap justify-between gap-2 px-1 text-[10px] uppercase tracking-wider text-muted-foreground">
              <span>{snapshot.engine.name} {snapshot.engine.version} · {snapshot.engine.implementation}</span>
              <span>Engine {snapshot.engineId.slice(0, 8)} · Rev {state.rev} · Seq {state.lastSeq}{state.droppedEvents > 0 ? ` · ${state.droppedEvents} dropped` : ""}</span>
            </footer>
          </>
        ) : (
          <section className="grid min-h-[420px] place-items-center rounded-2xl border border-dashed bg-card/30 p-8 text-center">
            <div className="max-w-md">
              <div className="mx-auto mb-4 grid size-16 place-items-center rounded-full border bg-muted/40"><Unplug className="size-7 text-muted-foreground" /></div>
              <h2 className="text-lg font-semibold">No engine session</h2>
              <p className="mt-2 text-sm text-muted-foreground">Start the optional host, then connect to receive live deck, mixer, and meter state. Nothing starts automatically.</p>
            </div>
          </section>
        )}
      </div>
      {!onRequestTrack && (
        <LibraryTrackPicker deck={pickerDeck} onClose={closePicker} onSelect={selectTrack} />
      )}
    </main>
  );
}

function StatusPill({ label, active, pending }: { label: string; active: boolean; pending: boolean }) {
  return (
    <span className="inline-flex h-8 items-center gap-2 rounded-full border bg-background px-3 text-xs font-medium">
      <span className={cn("size-2 rounded-full", pending ? "animate-pulse bg-muted-foreground" : active ? "bg-emerald-400 shadow-[0_0_8px_rgba(52,211,153,0.8)]" : "bg-muted-foreground/40")} />
      {label}
    </span>
  );
}
