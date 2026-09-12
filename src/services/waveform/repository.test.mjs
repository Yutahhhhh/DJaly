import test from 'node:test';
import assert from 'node:assert/strict';
import { normalizeTileRanges, normalizeWaveformManifest } from './manifest.ts';

test('normalizes the flat single-range manifest produced by v0.5.10', () => {
  assert.deepEqual(normalizeTileRanges([0, 3]), [[0, 3]]);
  const manifest = normalizeWaveformManifest({
    schemaVersion: 2, assetKey: 'asset', levels: [{ lod: 0, framesPerBin: 64, readyTileRanges: [0, 3], bandReadyTileRanges: [0, 3] }],
  });
  assert.deepEqual(manifest?.levels[0].readyTileRanges, [[0, 3]]);
  assert.deepEqual(manifest?.levels[0].bandReadyTileRanges, [[0, 3]]);
});

test('preserves valid ranges and discards malformed entries without throwing', () => {
  assert.deepEqual(normalizeTileRanges([[0, 2], [2, 5]]), [[0, 2], [2, 5]]);
  assert.deepEqual(normalizeTileRanges([0, 0]), []);
  assert.deepEqual(normalizeTileRanges([0, [1, 2], null, ['0', 2], [4, 3]]), [[1, 2]]);
  assert.equal(normalizeWaveformManifest(null), null);
  assert.equal(normalizeWaveformManifest({ schemaVersion: 1, assetKey: 'asset', levels: [] }), null);
});
