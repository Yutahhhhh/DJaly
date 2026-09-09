import test from 'node:test';
import assert from 'node:assert/strict';
import { frameNotification } from '../../../src/services/dj-engine/frame-notification.ts';

test('telemetry bursts render latest state once without accumulating callbacks', () => {
  const pending = new Map<number, FrameRequestCallback>(); let id = 0;
  const seen: number[] = [];
  const channel = frameNotification<number>(v => seen.push(v), cb => { pending.set(++id, cb); return id; }, key => { pending.delete(key); });
  for (let value = 0; value < 10000; value++) channel.push(value);
  assert.equal(pending.size, 1); assert.deepEqual(seen, []);
  const callback = [...pending.values()][0]; pending.clear(); callback(0);
  assert.deepEqual(seen, [9999]);
  channel.push(10000); assert.equal(pending.size, 1);
  channel.dispose(); assert.equal(pending.size, 0);
  channel.push(10001); callback(0); assert.deepEqual(seen, [9999]);
});

test('updates produced during delivery schedule the next frame', () => {
  const pending: FrameRequestCallback[] = []; const seen: number[] = [];
  const channel = frameNotification<number>(v => { seen.push(v); if (v === 1) channel.push(2); }, cb => { pending.push(cb); return pending.length; }, () => {});
  channel.push(1); pending.shift()!(0); assert.deepEqual(seen, [1]);
  pending.shift()!(16); assert.deepEqual(seen, [1, 2]); channel.dispose();
});

test('lifecycle notifications bypass and replace pending telemetry', () => {
  const pending = new Map<number, FrameRequestCallback>(); const seen: string[] = []; let id = 0;
  const channel = frameNotification<string>(v => seen.push(v), cb => { pending.set(++id, cb); return id; }, key => { pending.delete(key); });
  channel.push('position'); channel.flush('paused');
  assert.equal(pending.size, 0); assert.deepEqual(seen, ['paused']);
  channel.flush('recording'); assert.deepEqual(seen, ['paused', 'recording']);
  channel.dispose(); channel.flush('stale'); assert.equal(seen.length, 2);
});
