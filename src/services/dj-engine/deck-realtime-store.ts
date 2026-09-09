import { parseClockPoint, type DeckClockPoint } from '../../types/deck-performance.ts';
import { ClockMapping, presentPoint } from './transport-clock.ts';
class DeckRealtimeStore {
  readonly mapping = new ClockMapping();
  private engine = '';
  private points = new Map<string, DeckClockPoint>();
  reset(engine = '') { this.engine = engine; this.points.clear(); this.mapping.reset(); }
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
    }
  }
  invalidate(deck: string) { this.points.delete(deck); }
  position(deck: string | undefined, nowMs: number) {
    if (!deck) return null;
    const p = this.points.get(deck), mapped = this.mapping.at(nowMs);
    if (!p || !mapped) return null;
    const value = presentPoint(p,mapped.nativeUs);
    return {...value, positionMs:value.sourceFrame*1000/p.sourceSampleRateHz, uncertaintyUs:mapped.uncertaintyUs};
  }
}
export const deckRealtimeStore = new DeckRealtimeStore();
