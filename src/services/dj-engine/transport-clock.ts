import type { DeckClockPoint } from '../../types/deck-performance.ts';
/** Midpoint estimate with an explicit asymmetry bound; domains are never assumed equal. */
export class ClockMapping {
  private samples: { offset: number; uncertainty: number; at: number }[] = [];
  reset() { this.samples = []; }
  probe(t0: number, t1: number, t2: number, t3: number) {
    if (![t0,t1,t2,t3].every(Number.isFinite) || t3 < t0 || t2 < t1) return false;
    const uncertainty = ((t3-t0)*1000 - (t2-t1))/2;
    if (uncertainty < 0 || uncertainty > 50_000) return false;
    this.samples = this.samples.filter(s => t3 >= s.at && t3-s.at < 120_000).slice(-15);
    this.samples.push({offset: (t1+t2)/2-(t0+t3)*500, uncertainty, at:t3});
    return true;
  }
  at(nowMs: number) {
    const best = this.samples.filter(s => nowMs >= s.at && nowMs-s.at < 120_000).sort((a,b) => a.uncertainty-b.uncertainty)[0];
    return best ? {nativeUs:nowMs*1000+best.offset, uncertaintyUs:best.uncertainty} : null;
  }
}
export function presentPoint(point: DeckClockPoint, nativeUs: number) {
  const ageUs = Math.max(0, nativeUs-point.nativeMonoUs);
  // A block that crosses an unknown sub-block boundary has no safe slope.
  const horizon = point.scratching ? 12_000 : 50_000;
  const safe = point.interpolationSafe && point.discontinuity === null;
  const velocity = point.velocityRatioEnd ?? point.velocityRatioMean;
  const delta = safe && (point.transportPlaying || point.scratching) ? Math.min(ageUs,horizon)*velocity*point.sourceSampleRateHz/1e6 : 0;
  return {sourceFrame:point.sourceFrameEnd+delta, confidence:ageUs > horizon ? 'stale' : safe ? 'predicted' : 'boundary', trajectoryEpoch:point.trajectoryEpoch} as const;
}
