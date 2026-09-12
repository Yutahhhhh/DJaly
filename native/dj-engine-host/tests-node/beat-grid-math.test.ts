import test from "node:test";
import assert from "node:assert/strict";
import { barNumbers, bpmAt, lowerBeat, nearestBeat, scaleGrid, setDownbeat, setTempoFrom, shiftGrid, subdivideGrid } from "../../../src/components/play/beat-grid-math.ts";
import { buildBeatgridParams } from "../../../src/services/dj-engine/protocol.ts";
const grid = { bpm: 120, first_beat_ms: 100, beats_per_bar: 4, beat_times_ms: [100,600,1100,1700,2300,2900], beat_numbers: [3,4,1,2,3,4], source: "rekordbox" as const };
test("a 126 to 93 transition is authored once and preserves every earlier beat", () => {
  const base = { bpm: 126, first_beat_ms: 137, beats_per_bar: 4, source: "analysis" as const };
  const anchor = 137 + 64 * 60000 / 126;
  const edited = setTempoFrom(base, 93, anchor, 90_000);
  for (let i = 0; i < 64; i++) assert.equal(edited.beat_times_ms![i], 137 + i * 60000 / 126);
  assert.equal(edited.beat_times_ms![64], anchor);
  assert(Math.abs(edited.beat_times_ms![65] - anchor - 60000 / 93) < 1e-8);
  assert.equal(edited.bpm, 126); // stable track BPM, not a live display change
  assert.equal(edited.source, "manual");
  assert(Math.abs(bpmAt(edited, anchor) - 93) < 1e-8);
  const transported = buildBeatgridParams("A", "1", edited.bpm, edited.first_beat_ms, 4, edited.beat_times_ms, edited.beat_numbers);
  assert.deepEqual(transported.beatTimesMs, edited.beat_times_ms);
  const restored = JSON.parse(JSON.stringify(edited));
  assert.deepEqual(restored.beat_times_ms, edited.beat_times_ms);
  const second = setTempoFrom(restored, 110, 60_000, 90_000);
  assert.deepEqual(second.beat_times_ms!.filter(t => t < 60_000), edited.beat_times_ms!.filter(t => t < 60_000));
});
test("segment edit keeps imported bar phase and supports an off-grid edit point", () => {
  const edited = setTempoFrom(grid, 90, 1700, 5000);
  assert.deepEqual(edited.beat_times_ms!.slice(0, 4), [100,600,1100,1700]);
  assert.deepEqual(edited.beat_numbers!.slice(0, 4), [3,4,1,2]);
  const between = setTempoFrom(grid, 100, 1600, 5000);
  assert.deepEqual(between.beat_times_ms!.slice(0, 5), [100,600,1100,1600,2200]);
  assert.equal(grid.beat_times_ms[4], 2300);
  for (const bpm of [0,NaN,301]) assert.throws(() => setTempoFrom(grid,bpm,1700,5000));
  for (const anchor of [-1,5000,NaN]) assert.throws(() => setTempoFrom(grid,93,anchor,5000));
});
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
