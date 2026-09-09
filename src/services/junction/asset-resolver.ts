type AssetTrack = {trackId: string; assetId?: string; localTrackId?: number | null};
/** Remote numeric IDs never address the receiving computer's database. Only a
 * native cache-manifest resolution may associate an asset with a local row. */
export function localTrackId(track: AssetTrack | null | undefined): number | null {
  if (!track) return null;
  const id = track.assetId ? track.localTrackId : Number(track.trackId);
  return typeof id === 'number' && Number.isSafeInteger(id) && id > 0 ? id : null;
}
export function assetIdentity(track: AssetTrack): string { return track.assetId ?? track.trackId; }

/** Reject unbounded or malformed remote visual payloads before canvas work. */
export function assetWaveform(value: import('../../types/dj-engine').AssetWaveform | undefined) {
  if (!value || !Number.isFinite(value.bins_per_second) || value.bins_per_second <= 0 || value.bins_per_second > 1000
    || !Number.isFinite(value.duration_ms) || value.duration_ms <= 0
    || !Number.isFinite(value.amplitude_scale) || value.amplitude_scale <= 0) return undefined;
  const length = value.peaks?.length;
  if (!length || length > 2_000_000) return undefined;
  if (![value.peaks,value.low,value.mid,value.high].every(a => Array.isArray(a) && a.length === length && a.every(n => Number.isFinite(n) && n >= 0 && n <= value.amplitude_scale))) return undefined;
  return value;
}
