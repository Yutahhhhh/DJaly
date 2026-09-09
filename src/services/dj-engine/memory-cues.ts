import { assetIdentity } from '../junction/asset-resolver';
import { junctionLeaseKey } from '../junction/state';
import type { DeckId } from "../../types/dj-engine";
import { djEngineClient } from "./client";
export type MemoryCue = { positionMs: number; endMs?: number };
const key = (track: string) => `djaly.memoryCues.${track}`;
export function memoryCues(track: string, duration = Infinity): MemoryCue[] {
  try { const data = JSON.parse(localStorage.getItem(key(track)) ?? "[]"); return Array.isArray(data) ? data.filter((v): v is MemoryCue => v && Number.isFinite(v.positionMs) && v.positionMs >= 0 && v.positionMs < duration && (v.endMs === undefined || Number.isFinite(v.endMs) && v.endMs > v.positionMs && v.endMs <= duration)).slice(0,64).sort((a,b) => a.positionMs-b.positionMs) : []; } catch { return []; }
}
export async function memoryAction(deck: DeckId, action: "save" | "delete" | "previous" | "next") {
  const state = djEngineClient.getState().snapshot?.decks[deck];
  if (!state?.track) return;
  const {durationMs} = state.track;
  const trackId = assetIdentity(state.track);
  let points = memoryCues(trackId, durationMs);
  if (action === "save") {
    const cue: MemoryCue = state.loopRegion?.enabled ? { positionMs: state.loopRegion.startMs, endMs: state.loopRegion.endMs } : {positionMs:Math.max(0,state.positionMs)};
    if (cue.positionMs >= durationMs) return;
    points = points.filter(p => Math.abs(p.positionMs-cue.positionMs)>10);
    if (points.length >= 64) throw new Error("メモリーキューは1曲64件までです");
    points.push(cue);
  } else if (action === "delete") points = points.filter(p => Math.abs(p.positionMs-state.positionMs)>50);
  else {
    const point = action === "next" ? points.find(p => p.positionMs>state.positionMs+10) : points.reverse().find(p => p.positionMs<state.positionMs-10);
    if (!point) return;
    const lease = junctionLeaseKey();
    const session = djEngineClient.getSessionId(), generation = djEngineClient.getDeckGeneration(deck);
    const valid = () => lease === junctionLeaseKey() && session === djEngineClient.getSessionId() && generation === djEngineClient.getDeckGeneration(deck);
    await djEngineClient.seek(deck, point.positionMs);
    if (point.endMs !== undefined && valid()) { await djEngineClient.setLoop(deck, point.positionMs, point.endMs); if (valid()) await djEngineClient.enableLoop(deck, true); }
    return;
  }
  localStorage.setItem(key(trackId), JSON.stringify(points.sort((a,b) => a.positionMs-b.positionMs)));
  window.dispatchEvent(new CustomEvent("djaly:memory-cues", {detail:{trackId}}));
}
