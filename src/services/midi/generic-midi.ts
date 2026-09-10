import type { MidiAction } from "./ddj1000.ts";

export type GenericBinding = {
  id: string; input: { kind: "note" | "cc" | "cc14" | "pitchbend"; channel: number; number: number };
  encoding?: "button" | "absolute" | "relative-twos-complement";
  actionId: string; deck?: "A" | "B" | "C" | "D"; slot?: number;
  trigger?: "press" | "hold" | "toggle";
};
export type GenericMidiProfile = { schemaVersion: 1; adapterId: "generic-midi" | "ddj400" | "ddj1000"; bindings: GenericBinding[] };

const CONTROL: Record<string, string> = {
  "library.browse": "browse", "library.load": "load", "deck.play": "play", "deck.cue": "cue",
  "deck.sync": "sync", "deck.tempo": "tempo", "deck.jog": "jog", "deck.jog_touch": "touch",
  "deck.nudge": "nudge", "mixer.trim": "trim", "mixer.eq_low": "eqLow", "mixer.eq_mid": "eqMid",
  "mixer.eq_high": "eqHigh", "mixer.channel_fader": "gain", "mixer.crossfader": "crossfader",
  "mixer.filter": "filter", "mixer.cue": "pfl", "pad.hotcue": "hotcue", "loop.in": "loopIn",
  "loop.out": "loopOut", "loop.exit": "reloop", "loop.size": "loop",
};

export class GenericMidiDecoder {
  private held = new Set<string>();
  private msb = new Map<string, number>();
  private readonly profile: GenericMidiProfile;
  constructor(profile: GenericMidiProfile) { this.profile = profile; }
  reset() { this.held.clear(); this.msb.clear(); }
  feed(bytes: readonly number[]): MidiAction[] {
    const result: MidiAction[] = [];
    for (let offset = 0; offset + 2 < bytes.length; offset += 3) {
      const status = bytes[offset], number = bytes[offset + 1], raw = bytes[offset + 2];
      const type = status & 0xf0, channel = status & 0x0f;
      const wireKind = type === 0xb0 ? "cc" : type === 0x90 || type === 0x80 ? "note" : type === 0xe0 ? "pitchbend" : null;
      if (!wireKind) continue;
      for (const binding of this.profile.bindings) {
        if (binding.input.channel !== channel) continue;
        const cc14 = binding.input.kind === "cc14" && wireKind === "cc" && (number === binding.input.number || number === binding.input.number + 32);
        const pitchbend = binding.input.kind === "pitchbend" && wireKind === "pitchbend";
        if (!cc14 && !pitchbend && (binding.input.kind !== wireKind || binding.input.number !== number)) continue;
        if (cc14 && number === binding.input.number) { this.msb.set(binding.id, raw); continue; }
        const pressed = wireKind === "note" && type === 0x90 && raw > 0;
        const key = binding.id;
        if (wireKind === "note" && this.held.has(key) === pressed) continue;
        if (wireKind === "note") pressed ? this.held.add(key) : this.held.delete(key);
        if (binding.trigger === "press" && !pressed) continue;
        const high = cc14 ? this.msb.get(binding.id) : undefined;
        if (cc14 && high === undefined) continue;
        if (cc14) this.msb.delete(binding.id);
        const value = cc14 ? (high! * 128 + raw) / 16383
          : wireKind === "pitchbend" ? (raw * 128 + number) / 16383
          : binding.encoding === "relative-twos-complement" ? (raw < 64 ? raw : raw - 128)
          : binding.encoding === "button" || wireKind === "note" ? raw : raw / 127;
        const control = CONTROL[binding.actionId];
        if (control) result.push({ control, deck: binding.deck, slot: binding.slot, value, pressed });
      }
    }
    return result;
  }
}

export function parseGenericProfile(raw: string | null): GenericMidiProfile | null {
  if (!raw) return null;
  try {
    const value = JSON.parse(raw) as GenericMidiProfile;
    if (value.schemaVersion !== 1 || !Array.isArray(value.bindings)) return null;
    return value;
  } catch { return null; }
}
