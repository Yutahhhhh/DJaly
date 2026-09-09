import test from "node:test";
import assert from "node:assert/strict";
import { KeyedTaskQueue } from "../../../src/services/dj-engine/keyed-task-queue.ts";
const tick = () => new Promise<void>(r => setImmediate(r));
test("same-track save waits for pending load, while other tracks remain independent", async () => {
  const queue = new KeyedTaskQueue(), events: string[] = [];
  let loaded!: () => void;
  const load = queue.run(1, async () => { events.push("load-start"); await new Promise<void>(r => { loaded = r; }); events.push("load-ready"); });
  const save = queue.run(1, async () => { events.push("save-all-loaded"); });
  await queue.run(2, async () => { events.push("other-track"); });
  assert.deepEqual(events,["load-start","other-track"]);
  loaded(); await Promise.all([load,save]);
  assert.deepEqual(events,["load-start","other-track","load-ready","save-all-loaded"]);
});
test("failed load does not deadlock the next same-track operation", async () => {
  const queue = new KeyedTaskQueue();
  await assert.rejects(queue.run(1, async()=>{throw new Error("decode failed")}), /decode failed/);
  await tick(); assert.equal(await queue.run(1,async()=>"saved"),"saved");
});
