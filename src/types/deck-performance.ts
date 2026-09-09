import type { DeckId } from './dj-engine.ts';
export interface DeckClockPoint {
  schema: 2; engineEpoch: string; audioConfigEpoch: number; deck: DeckId;
  loadGeneration: number; trajectoryEpoch: number; sequence: number;
  outputFrameEnd: number; outputFrames: number; outputSampleRateHz: number;
  sourceFrameStart: number; sourceFrameEnd: number; sourceSampleRateHz: number;
  nativeMonoUs: number; timestampReference: 'deck-postprocess-observed';
  velocityRatioMean: number; velocityRatioEnd: number | null;
  transportPlaying: boolean; scratching: boolean; appliedInputSeq: number;
  discontinuity: null | 'seek' | 'cue' | 'loop-wrap' | 'load' | 'slip-return';
  interpolationSafe: boolean;
}
export function parseClockPoint(value: unknown): DeckClockPoint | null {
  if (!value || typeof value !== 'object') return null;
  const p = value as Record<string, unknown>;
  if (p.schema !== 2 || typeof p.engineEpoch !== 'string' || !['A','B','C','D'].includes(String(p.deck))
    || p.timestampReference !== 'deck-postprocess-observed' || typeof p.transportPlaying !== 'boolean'
    || typeof p.scratching !== 'boolean' || typeof p.interpolationSafe !== 'boolean'
    || ![null,'seek','cue','loop-wrap','load','slip-return'].includes(p.discontinuity as null)) return null;
  for (const key of ['audioConfigEpoch','loadGeneration','trajectoryEpoch','sequence','outputFrameEnd','outputFrames','appliedInputSeq'])
    if (!Number.isSafeInteger(p[key]) || (p[key] as number) < 0) return null;
  for (const key of ['sourceFrameStart','sourceFrameEnd','sourceSampleRateHz','outputSampleRateHz','nativeMonoUs','velocityRatioMean'])
    if (typeof p[key] !== 'number' || !Number.isFinite(p[key])) return null;
  if ((p.sourceSampleRateHz as number) <= 0 || (p.outputSampleRateHz as number) <= 0 || (p.outputFrames as number) <= 0
    || Math.abs(p.sourceFrameEnd as number) > Number.MAX_SAFE_INTEGER || Math.abs(p.sourceFrameStart as number) > Number.MAX_SAFE_INTEGER
    || p.velocityRatioEnd !== null && (typeof p.velocityRatioEnd !== 'number' || !Number.isFinite(p.velocityRatioEnd))) return null;
  return p as unknown as DeckClockPoint;
}
