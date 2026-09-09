export type SeekPreview = { position: number; at: number; until: number };

/** Pointer capture alone must never freeze a still-playing transport. */
export function waveformPlayhead(
  telemetry: { position: number; receivedAt: number }, preview: SeekPreview | null,
  now: number, playing: boolean, rate: number, durationMs: number,
  /** Audio transport includes silence before zero. Only overview clips its viewport. */
  minPositionMs = Number.NEGATIVE_INFINITY,
) {
  const activePreview = preview && now < preview.until;
  const base = activePreview ? preview.position : telemetry.position;
  const elapsed = activePreview ? Math.max(0, now - preview.at) : Math.min(200, Math.max(0, now - telemetry.receivedAt));
  return Math.max(minPositionMs, Math.min(durationMs, base + (playing ? elapsed * rate : 0)));
}
