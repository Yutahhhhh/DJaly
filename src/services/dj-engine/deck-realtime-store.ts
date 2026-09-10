import { parseClockPoint, type DeckClockPoint } from '../../types/deck-performance.ts';
import { ClockMapping, presentPoint } from './transport-clock.ts';
export class DeckRealtimeStore {
  readonly mapping = new ClockMapping();
  private engine = '';
  private points = new Map<string, DeckClockPoint>();
  private history = new Map<string, DeckClockPoint[]>();
  private presentationDelayMs = 0;
  setPresentationDelay(ms: number) { this.presentationDelayMs = Number.isFinite(ms) ? Math.max(-50,Math.min(500,ms)) : 0; }
  reset(engine = '') { this.engine = engine; this.points.clear(); this.history.clear(); this.mapping.reset(); }
  ingest(data: unknown, engine: string) {
    if (engine !== this.engine || !data || typeof data !== 'object') return;
    const points = (data as {points?:unknown}).points;
    if (!Array.isArray(points) || points.length > 1024) return;
    for (const value of points) {
      const point = parseClockPoint(value);
      if (!point || point.engineEpoch !== engine) continue;
      const old = this.points.get(point.deck);
      if (old && (point.sequence <= old.sequence || point.loadGeneration < old.loadGeneration || point.audioConfigEpoch < old.audioConfigEpoch)) continue;
      this.points.set(point.deck,point);
      const history = old && old.loadGeneration === point.loadGeneration && old.audioConfigEpoch === point.audioConfigEpoch
        ? this.history.get(point.deck) ?? [] : [];
      history.push(point);
      if (history.length > 128) history.shift();
      this.history.set(point.deck,history);
    }
  }
  invalidate(deck: string) { this.points.delete(deck); this.history.delete(deck); }
  position(deck: string | undefined, nowMs: number, presentationDelayMs = this.presentationDelayMs) {
    if (!deck) return null;
    const p = this.points.get(deck), mapped = this.mapping.at(nowMs);
    if (!p || !mapped) return null;
    const nativeUs = mapped.nativeUs - (Number.isFinite(presentationDelayMs) ? Math.max(-500,Math.min(500,presentationDelayMs))*1000 : 0);
    const history = this.history.get(deck) ?? [];
    // Evaluate the source trajectory at the requested presentation time. A
    // latency correction is never multiplied by the latest (possibly reversed)
    // velocity across a seek, stop, or loop boundary.
    const nextIndex = history.findIndex(point => point.nativeMonoUs >= nativeUs);
    let value;
    if (nextIndex >= 0 && history[nextIndex].nativeMonoUs === nativeUs) {
      value = presentPoint(history[nextIndex],nativeUs);
    } else if (nextIndex > 0) {
      const before = history[nextIndex-1], after = history[nextIndex];
      const safe = after.interpolationSafe && before.interpolationSafe && after.discontinuity === null
        && after.trajectoryEpoch === before.trajectoryEpoch && after.nativeMonoUs > before.nativeMonoUs;
      const ratio = safe ? (nativeUs-before.nativeMonoUs)/(after.nativeMonoUs-before.nativeMonoUs) : 0;
      value = {sourceFrame:before.sourceFrameEnd+(after.sourceFrameEnd-before.sourceFrameEnd)*ratio,
        confidence:safe?'interpolated':'boundary',trajectoryEpoch:before.trajectoryEpoch};
    } else if (nextIndex === 0 && nativeUs < history[0].nativeMonoUs) {
      value = {sourceFrame:history[0].sourceFrameEnd,confidence:'stale',trajectoryEpoch:history[0].trajectoryEpoch};
    } else value = presentPoint(p,nativeUs);
    return {...value, positionMs:value.sourceFrame*1000/p.sourceSampleRateHz, uncertaintyUs:mapped.uncertaintyUs};
  }
}
export const deckRealtimeStore = new DeckRealtimeStore();
