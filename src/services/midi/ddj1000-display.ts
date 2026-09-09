import type { DeckState } from "../../types/dj-engine";
export type JogAssets = { waveform: number[]; artwork: number[]; version: number };
export function jogWaveform(peaks: readonly number[]): number[] {
  const out = [0x80];
  for (let column = 0; column < 600; column++) {
    const start = Math.floor(column * peaks.length / 600), end = Math.max(start + 1, Math.floor((column + 1) * peaks.length / 600));
    let peak = 0;
    for (let i = start; i < Math.min(peaks.length, end); i++) if (Number.isFinite(peaks[i])) peak = Math.max(peak, Math.abs(peaks[i]));
    const height = Math.round(Math.min(1, peak) * 31);
    // DDJ-1000's encoded blue palette entry; not RGB bytes.
    out.push(0x11, 0x0b, 0x17, 0x14, height, Math.round(height / 2), 0);
  }
  return out;
}
export function jogFrame(deck: DeckState | undefined, token: string, assets?: JogAssets) {
  const durationMs = Math.max(0, Math.min(0xffffff, deck?.track?.durationMs ?? 0));
  const trackBpm = deck?.track?.bpm;
  const bpm = Math.max(0, Math.min(255.9, trackBpm && trackBpm > 0
    ? trackBpm * (deck?.rate ?? 1) : deck?.effectiveBpm ?? 0));
  const actual = deck?.track?.beatTimesMs?.filter(t => Number.isFinite(t) && t >= 0 && t <= durationMs);
  let beats: number[] = actual?.length ? actual : [];
  if (!beats.length && durationMs > 0) {
    const interval = 60000 / (deck?.track?.bpm || bpm || 120);
    const offset = Math.max(0, deck?.track?.beatgridOffsetMs ?? 0);
    const count = Math.min(100000, Math.max(0, Math.ceil((durationMs - offset) / interval)));
    beats = Array.from({ length: count }, (_, i) => offset + i * interval);
  }
  if (beats.length > 2000) beats = Array.from({length: 2000}, (_, i) => beats[Math.floor(i * (beats.length - 1) / 1999)]);
  return {
    token: deck?.track ? token : "", positionMs: Math.max(0, deck?.positionMs ?? 0), durationMs, bpm,
    rate: Math.max(0, Math.min(4, deck?.rate ?? 1)), playing: deck?.status === "playing" && !deck?.scratching,
    master: Boolean(deck?.track && deck.syncLeader === deck.deck), beats,
    cues: (deck?.hotCues ?? []).map(c => c == null ? null : Math.max(0, Math.min(durationMs, c))),
    waveform: assets?.waveform ?? [], artwork: assets?.artwork ?? [], assetVersion: assets?.version ?? 0,
  };
}
// Suppress the MIDI screen overlay while HID owns the displays. Button/pad
// LEDs remain MIDI-driven. Re-sending either picture over the other flickers.
export function isJogScreenMidi([status, key]: number[]): boolean {
  const channel = status & 15;
  return channel < 4 && ((status & 0xf0) === 0xb0 && [0x14,0x34,0x15,0x35,0x16,0x36,0x17,0x37].includes(key)
    || (status & 0xf0) === 0x90 && [0x42,0x43,0x44,0x49,0x4a,0x59,0x5a,0x5b,0x5d].includes(key))
    || status === 0x9f && key < 4;
}
