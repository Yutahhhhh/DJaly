import test from "node:test";
import assert from "node:assert/strict";

import {
  cuePositions,
  PerformanceMetadataConflictError,
  persistCue,
  persistLoop,
  type PerformanceMetadataRepository,
} from "../../../src/services/performance-cue-metadata.ts";
import type {
  PerformanceMetadata,
  PerformanceMetadataWrite,
} from "../../../src/types/performance-metadata.ts";

const metadata = (changes: Partial<PerformanceMetadata> = {}): PerformanceMetadata => ({
  track_id: 7,
  revision: 4,
  cue_points: [],
  loops: [],
  beat_grid: { bpm: 120, first_beat_ms: 10, beats_per_bar: 4 },
  created_at: null,
  updated_at: null,
  ...changes,
});

class RecordingRepo implements PerformanceMetadataRepository {
  readonly writes: PerformanceMetadataWrite[] = [];
  getCalls = 0;
  private readonly onReplace: (
    write: PerformanceMetadataWrite,
    call: number,
  ) => PerformanceMetadata;
  private readonly onGet: (call: number) => PerformanceMetadata;

  constructor(
    onReplace: (write: PerformanceMetadataWrite, call: number) => PerformanceMetadata,
    onGet: (call: number) => PerformanceMetadata = () => metadata(),
  ) {
    this.onReplace = onReplace;
    this.onGet = onGet;
  }

  async get(): Promise<PerformanceMetadata> {
    this.getCalls += 1;
    return this.onGet(this.getCalls);
  }

  async replace(_trackId: number, write: PerformanceMetadataWrite): Promise<PerformanceMetadata> {
    this.writes.push(write);
    return this.onReplace(write, this.writes.length);
  }
}

const conflict = () => Object.assign(new Error("revision conflict"), { status: 409 });

test("cue persistence preserves labels/colors and clearing removes only the target slot", async () => {
  const baseline = metadata({
    cue_points: [
      { slot: 0, position_ms: 100, label: "Drop", color: "#f00" },
      { slot: 2, position_ms: 300, label: "C", color: null },
    ],
  });
  const repo = new RecordingRepo((write) => metadata({ ...write, revision: 5 }));

  await persistCue(repo, 7, baseline, 0, 150);
  assert.deepEqual(repo.writes[0].cue_points, [
    { slot: 0, position_ms: 150, label: "Drop", color: "#f00" },
    { slot: 2, position_ms: 300, label: "C", color: null },
  ]);
  await persistCue(repo, 7, baseline, 0, null);
  assert.deepEqual(repo.writes[1].cue_points, [
    { slot: 2, position_ms: 300, label: "C", color: null },
  ]);

  await persistCue(repo, 7, metadata(), 7, 800);
  assert.deepEqual(repo.writes[2].cue_points, [
    { slot: 7, position_ms: 800, label: "H", color: null },
  ]);
});

test("cue conflict rebases onto unrelated concurrent metadata", async () => {
  const baseline = metadata({
    cue_points: [{ slot: 0, position_ms: 100, label: "A", color: null }],
  });
  const latest = metadata({
    revision: 5,
    cue_points: [
      { slot: 0, position_ms: 100, label: "A", color: null },
      { slot: 1, position_ms: 250, label: "Second", color: "blue" },
    ],
    loops: [{ id: "other", start_ms: 20, end_ms: 40, label: "Other" }],
    beat_grid: { bpm: 128, first_beat_ms: 15, beats_per_bar: 3 },
  });
  const repo = new RecordingRepo(
    (write, call) => {
      if (call === 1) throw conflict();
      return metadata({ ...write, revision: 6 });
    },
    () => latest,
  );

  await persistCue(repo, 7, baseline, 0, 175);
  assert.equal(repo.writes[0].revision, 4);
  assert.equal(repo.writes[1].revision, 5);
  assert.deepEqual(repo.writes[1].cue_points, [
    { slot: 0, position_ms: 175, label: "A", color: null },
    { slot: 1, position_ms: 250, label: "Second", color: "blue" },
  ]);
  assert.deepEqual(repo.writes[1].loops, latest.loops);
  assert.deepEqual(repo.writes[1].beat_grid, latest.beat_grid);
});

test("same-slot concurrent cue edit is not overwritten", async () => {
  const baseline = metadata({
    cue_points: [{ slot: 3, position_ms: 100, label: "D", color: null }],
  });
  const latest = metadata({
    revision: 5,
    cue_points: [{ slot: 3, position_ms: 110, label: "Edited", color: "red" }],
  });
  const repo = new RecordingRepo(() => { throw conflict(); }, () => latest);

  await assert.rejects(
    persistCue(repo, 7, baseline, 3, 200),
    PerformanceMetadataConflictError,
  );
  assert.equal(repo.writes.length, 1);
  assert.equal(repo.getCalls, 1);
});

test("non-conflict errors propagate without retry", async () => {
  const unavailable = Object.assign(new Error("unavailable"), { status: 503 });
  const repo = new RecordingRepo(() => { throw unavailable; });

  await assert.rejects(persistCue(repo, 7, metadata(), 0, 10), (error) => error === unavailable);
  assert.equal(repo.writes.length, 1);
  assert.equal(repo.getCalls, 0);
});

test("conflict retries are bounded", async () => {
  const repo = new RecordingRepo(
    () => { throw conflict(); },
    (call) => metadata({ revision: 4 + call }),
  );

  await assert.rejects(
    persistCue(repo, 7, metadata(), 0, 10),
    /after 3 conflict retries/,
  );
  assert.equal(repo.writes.length, 4);
  assert.equal(repo.getCalls, 3);
});

test("loop persistence updates by id while preserving cues, grid, and other loops", async () => {
  const baseline = metadata({
    cue_points: [{ slot: 1, position_ms: 200, label: "B", color: null }],
    loops: [
      { id: "chorus", start_ms: 100, end_ms: 200, label: "Chorus" },
      { id: "outro", start_ms: 300, end_ms: 400, label: "Outro" },
    ],
  });
  const repo = new RecordingRepo((write) => metadata({ ...write, revision: 5 }));

  await persistLoop(repo, 7, baseline, {
    id: "chorus",
    start_ms: 110,
    end_ms: 230,
    label: "New chorus",
  });
  assert.deepEqual(repo.writes[0].cue_points, baseline.cue_points);
  assert.deepEqual(repo.writes[0].beat_grid, baseline.beat_grid);
  assert.deepEqual(repo.writes[0].loops, [
    { id: "chorus", start_ms: 110, end_ms: 230, label: "New chorus" },
    baseline.loops[1],
  ]);
});

test("same-id concurrent loop edit conflicts, while unrelated edits rebase", async () => {
  const baseline = metadata({
    loops: [{ id: "loop", start_ms: 10, end_ms: 20, label: "Loop" }],
  });
  const changed = metadata({
    revision: 5,
    loops: [{ id: "loop", start_ms: 11, end_ms: 20, label: "Loop" }],
  });
  const conflictingRepo = new RecordingRepo(() => { throw conflict(); }, () => changed);
  await assert.rejects(
    persistLoop(conflictingRepo, 7, baseline, { id: "loop", start_ms: 10, end_ms: 30, label: "Long" }),
    PerformanceMetadataConflictError,
  );
  assert.equal(conflictingRepo.writes.length, 1);

  const latest = metadata({
    revision: 5,
    cue_points: [{ slot: 5, position_ms: 500, label: "F", color: null }],
    loops: baseline.loops,
  });
  const rebasingRepo = new RecordingRepo(
    (write, call) => {
      if (call === 1) throw conflict();
      return metadata({ ...write, revision: 6 });
    },
    () => latest,
  );
  await persistLoop(rebasingRepo, 7, baseline, { id: "new", start_ms: 30, end_ms: 40, label: "New" });
  assert.deepEqual(rebasingRepo.writes[1].cue_points, latest.cue_points);
  assert.equal(rebasingRepo.writes[1].loops.length, 2);
});

test("malformed cue and loop inputs are rejected before repository access", () => {
  const repo = new RecordingRepo((write) => metadata({ ...write }));
  for (const slot of [-1, 16, 1.5, Number.NaN]) {
    assert.throws(() => persistCue(repo, 7, metadata(), slot, 10));
  }
  for (const position of [-1, Number.NaN, Number.POSITIVE_INFINITY]) {
    assert.throws(() => persistCue(repo, 7, metadata(), 0, position));
  }
  for (const loop of [
    { id: "", start_ms: 0, end_ms: 1, label: "x" },
    { id: "x", start_ms: -1, end_ms: 1, label: "x" },
    { id: "x", start_ms: 1, end_ms: 1, label: "x" },
    { id: "x", start_ms: 1, end_ms: Number.NaN, label: "x" },
  ]) assert.throws(() => persistLoop(repo, 7, metadata(), loop));
  assert.equal(repo.writes.length, 0);
});

test("cuePositions returns exactly eight entries and rejects malformed stored cues", () => {
  assert.deepEqual(cuePositions(metadata({
    cue_points: [
      { slot: 0, position_ms: 0, label: "A", color: null },
      { slot: 7, position_ms: 1_000, label: "H", color: null },
    ],
  }), 1_001), [0, null, null, null, null, null, null, 1_000]);

  for (const cue_points of [
    [{ slot: 16, position_ms: 1, label: "x", color: null }],
    [{ slot: 1, position_ms: -1, label: "x", color: null }],
    [{ slot: 1, position_ms: Number.NaN, label: "x", color: null }],
    [{ slot: 1, position_ms: 1_001, label: "x", color: null }],
    [{ slot: 1, position_ms: 1_000, label: "x", color: null }],
    [
      { slot: 1, position_ms: 1, label: "x", color: null },
      { slot: 1, position_ms: 2, label: "y", color: null },
    ],
  ]) assert.throws(() => cuePositions(metadata({ cue_points }), 1_000));
  assert.throws(() => cuePositions(metadata(), Number.NaN));
});

 test("cue slots I through P persist and expand the legacy eight-slot array", async () => {
 const repo = new RecordingRepo(write => metadata({...write}));
 const saved = await persistCue(repo,7,metadata(),15,500);
 assert.equal(saved.cue_points.find(c=>c.slot===15)?.position_ms,500);
 const positions=cuePositions(saved,1000);assert.equal(positions.length,16);assert.equal(positions[15],500);
 });
