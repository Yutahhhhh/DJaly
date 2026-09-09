import test from "node:test";
import assert from "node:assert/strict";
import { LatestCommandQueue } from "../../../src/services/dj-engine/latest-command-queue.ts";

const tick = () => new Promise<void>((resolve) => setImmediate(resolve));
test("FX release survives a failed activation reply without growing the queue", async () => {
  const sent: boolean[] = [];
  let fail!: (error: Error) => void;
  const queue = new LatestCommandQueue<boolean>(value => {
    sent.push(value);
    return value ? new Promise((_, reject) => { fail = reject; }) : Promise.resolve();
  }, true);
  const active = queue.enqueue(true);
  const rejected = assert.rejects(active, /lost reply/);
  await tick();
  const released = queue.enqueue(false);
  fail(new Error("lost reply"));
  await Promise.all([rejected, released]);
  assert.deepEqual(sent, [true, false]);
});
test("slow engine keeps only one in-flight seek and the final pointer target", async () => {
  const sent: number[] = []; const replies: (() => void)[] = [];
  const queue = new LatestCommandQueue<number>((value) => {
    sent.push(value); return new Promise<void>((resolve) => replies.push(resolve));
  });
  const first = queue.enqueue(0); await tick();
  const pending = queue.enqueue(1);
  for (let position = 2; position <= 1000; position++) assert.equal(queue.enqueue(position), pending);
  assert.deepEqual(sent, [0]);
  replies.shift()!(); await first; await tick();
  assert.deepEqual(sent, [0, 1000]);
  replies.shift()!(); await pending;
});

test("track/session cleanup discards queued stale targets", async () => {
  const sent: number[] = []; let reply!: () => void;
  const queue = new LatestCommandQueue<number>((value) => { sent.push(value); return new Promise<void>((resolve) => { reply = resolve; }); });
  const first = queue.enqueue(1); await tick();
  const discarded = queue.enqueue(2); queue.clear(); await discarded;
  reply(); await first; await tick(); assert.deepEqual(sent, [1]);
});

test("rejection rejects both active and pending callers; retry works without a stuck pump", async () => {
  let fail!: (error: Error) => void;
  let count = 0;
  const queue = new LatestCommandQueue<number>(() => {
    if (++count > 1) return Promise.resolve();
    return new Promise((_, reject) => { fail = reject; });
  });
  const first = queue.enqueue(1); await tick(); const last = queue.enqueue(2);
  const firstError = assert.rejects(first, /unavailable/), lastError = assert.rejects(last, /unavailable/);
  fail(new Error("unavailable")); await Promise.all([firstError, lastError]);
  await queue.enqueue(3); assert.equal(count, 2);
});

test("new input when the first promise resolves cannot be stranded", async () => {
  const sent: number[] = [];
  const queue = new LatestCommandQueue<number>(async (value) => { sent.push(value); });
  await queue.enqueue(1).then(() => queue.enqueue(2));
  assert.deepEqual(sent, [1, 2]);
});
