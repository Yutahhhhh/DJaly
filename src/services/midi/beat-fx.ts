// Official DDJ-1000 selector NOTE 0x20 + index, MIDI channel 5.
export const BEAT_FX = [
  ["lowcutecho", "LOW CUT ECHO"], ["echo", "ECHO"], ["mtdelay", "MT DELAY"],
  ["spiral", "SPIRAL"], ["reverb", "REVERB"], ["tremolo", "TRANS"],
  ["enigmajet", "ENIGMA JET"], ["flanger", "FLANGER"], ["phaser", "PHASER"],
  ["pitchshift", "PITCH"], ["sliproll", "SLIP ROLL"], ["roll", "ROLL"],
  ["mobiussaw", "MOBIUS SAW"], ["mobiustri", "MOBIUS TRI"],
] as const;
export function beatFxMaxBeats(effect: string): number {
  if (["echo","lowcutecho","mtdelay","spiral","enigmajet","sliproll","roll","mobiussaw","mobiustri"].includes(effect)) return 2;
  return effect === "tremolo" ? 4 : 16;
}
