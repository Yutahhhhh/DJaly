import type { PadEffect } from "../../types/dj-engine";
export type PadPreset = { effect: PadEffect; mix: number; depth: number };
// Independent software presets for each mode/page. These are plumdeck presets,
// not a claim to reproduce rekordbox's user-editable effect assignments.
const first: PadEffect[] = ["echo","reverb","flanger","filter","phaser","autopan","bitcrusher","distortion"];
const second: PadEffect[] = ["tremolo","moogladder4filter","reverb","echo","phaser","flanger","autopan","bitcrusher"];
export function padPreset(mode = 1, slot = 0): PadPreset {
  const page = (slot >> 3) & 1;
  return {effect:(mode === 5 ? second : first)[((slot & 7) + page * 4) % 8],mix:page ? 0.75:0.5,depth:page ? 0.85:0.5};
}
export const BEAT_LOOP_PAGES = [[.125,.25,.5,1,2,4,8,16],[.125,.25,.5,1,8,16,32,64]];
export const BEAT_JUMP_PAGES = [[-1,1,-2,2,-4,4,-8,8],[-8,8,-16,16,-32,32,-64,64]];
export function keyPad(page: number, pad: number): number | null {
  const value = [-8,0][page] + (pad & 7);
  return Number.isFinite(value) && value <= 12 ? value : null;
}
