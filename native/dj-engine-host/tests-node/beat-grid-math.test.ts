import test from "node:test";
import assert from "node:assert/strict";
import { barNumbers, lowerBeat, nearestBeat, scaleGrid, setDownbeat, shiftGrid, subdivideGrid } from "../../../src/components/play/beat-grid-math.ts";
import { buildBeatgridParams } from "../../../src/services/dj-engine/protocol.ts";
const grid = { bpm: 120, first_beat_ms: 100, beats_per_bar: 4, beat_times_ms: [100,600,1100,1700,2300,2900], beat_numbers: [3,4,1,2,3,4], source: "rekordbox" as const };
test("bar labels honor imported phase resets rather than inventing an index-based downbeat",()=>{
  assert.deepEqual(barNumbers(6,[3,4,1,2,1,2],4),[1,1,2,2,3,3]);
  assert.deepEqual(barNumbers(3,[1,1,1],4),[1,2,3]);
});
test("exact imported beat timestamps survive transport without constant-BPM fitting", () => {
  assert.deepEqual(buildBeatgridParams("A", "1", 120, 100, 4, grid.beat_times_ms, grid.beat_numbers).beatTimesMs, grid.beat_times_ms);
  assert.equal(lowerBeat(grid.beat_times_ms, 1600), 3);
  assert.equal(nearestBeat(grid, 1620), 1700);
});
test("whole-grid shift keeps variable beat intervals and original input immutable", () => {
  const shifted = shiftGrid(grid, 25, 4000);
  assert.deepEqual(shifted.beat_times_ms, [125,625,1125,1725,2325,2925]);
  assert.deepEqual(shifted.beat_numbers, grid.beat_numbers);
  assert.equal(shifted.source, "manual"); assert.equal(grid.first_beat_ms, 100);
});
test("tempo edits keep the selected anchor beat exactly fixed", () => {
  const scaled = scaleGrid(grid, 100, 1100, 5000);
  assert(scaled.beat_times_ms?.includes(1100));
  assert.deepEqual(scaled.beat_times_ms, [500,1100,1820,2540,3260]);
});
test("downbeat assignment aligns closest real beat, retaining variable intervals", () => {
  const fixed = setDownbeat(grid, 1725, 4000);
  assert.equal(fixed.beat_times_ms?.[3], 1725); assert.equal(fixed.beat_numbers?.[3], 1);
  assert.equal(fixed.beat_times_ms![4] - fixed.beat_times_ms![3], 600);
});
test("double/half tempo changes beat density rather than stretching the whole song", () => {
  const doubled = subdivideGrid(grid, 2, 1100);
  assert.equal(doubled.beat_times_ms?.length, 11);
  assert.equal(doubled.beat_times_ms?.at(-1), 2900);
  assert.deepEqual(subdivideGrid(doubled, 0.5, 1100).beat_times_ms, grid.beat_times_ms);
});
test("malformed variable grids are rejected before sending to the engine", () => {
  for (const beats of [[10], [10,10], [20,10], [-1,10], [0,NaN]]) assert.throws(() => buildBeatgridParams("A", "1",120,0,4,beats));
  assert.throws(() => buildBeatgridParams("A","1",120,0,4,[0,500],[1]));
  assert.throws(() => buildBeatgridParams("A","1",120,0,4,[0,500],[1,17]));
});
