export function normalizeTileRanges(value: unknown): [number, number][] {
  if (!Array.isArray(value)) return [];
  // v0.5.10's Qt initializer could publish a single range as [from, to]
  // instead of [[from, to]]. Accept it so an already-open/cached waveform
  // cannot crash the entire Play workspace during an upgrade.
  const ranges: unknown[] = value.length === 2 && value.every(Number.isFinite) ? [value] : value;
  return ranges.flatMap((range) => Array.isArray(range) && range.length === 2
    && range.every(Number.isFinite) && range[0] >= 0 && range[1] > range[0]
    ? [[range[0], range[1]] as [number, number]] : []);
}

export type NormalizedWaveformManifest = {
  schemaVersion: 2;
  assetKey: string;
  levels: { lod: number; framesPerBin: number; readyTileRanges: [number, number][]; bandReadyTileRanges: [number, number][]; [key: string]: unknown }[];
  [key: string]: unknown;
};

export function normalizeWaveformManifest(value: unknown): NormalizedWaveformManifest | null {
  if (!value || typeof value !== "object") return null;
  const manifest = value as Partial<NormalizedWaveformManifest>;
  if (manifest.schemaVersion !== 2 || typeof manifest.assetKey !== "string" || !Array.isArray(manifest.levels)) return null;
  return {
    ...manifest,
    schemaVersion: 2,
    assetKey: manifest.assetKey,
    levels: manifest.levels.flatMap((level) => level && Number.isInteger(level.lod) && Number.isFinite(level.framesPerBin)
      ? [{ ...level, readyTileRanges: normalizeTileRanges(level.readyTileRanges), bandReadyTileRanges: normalizeTileRanges(level.bandReadyTileRanges) }]
      : []),
  };
}
