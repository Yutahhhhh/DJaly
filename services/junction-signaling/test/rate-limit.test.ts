import { test } from "node:test";
import assert from "node:assert/strict";
import { TokenBucket, AttemptCounter, StrikeCounter } from "../src/rate-limit.js";

test("TokenBucket allows up to capacity then blocks", () => {
  const bucket = new TokenBucket(3, 1, 0);
  assert.equal(bucket.take(1, 0), true);
  assert.equal(bucket.take(1, 0), true);
  assert.equal(bucket.take(1, 0), true);
  assert.equal(bucket.take(1, 0), false);
});

test("TokenBucket refills over time", () => {
  const bucket = new TokenBucket(2, 10, 0); // 10 tokens/sec
  assert.equal(bucket.take(2, 0), true);
  assert.equal(bucket.take(1, 0), false);
  // 200ms later, +2 tokens at 10/sec
  assert.equal(bucket.take(1, 200), true);
});

test("TokenBucket never exceeds capacity", () => {
  const bucket = new TokenBucket(2, 100, 0);
  bucket.take(0, 100_000); // force a big refill check
  assert.ok(bucket.remaining <= 2);
});

test("AttemptCounter blocks after maxAttempts failures within the window", () => {
  const counter = new AttemptCounter(60_000, 3);
  const key = "room-a";
  assert.equal(counter.recordFailure(key, 0), false);
  assert.equal(counter.recordFailure(key, 1), false);
  assert.equal(counter.recordFailure(key, 2), true);
  assert.equal(counter.isBlocked(key, 3), true);
});

test("AttemptCounter window resets after it elapses", () => {
  const counter = new AttemptCounter(1000, 2);
  const key = "room-b";
  counter.recordFailure(key, 0);
  counter.recordFailure(key, 1);
  assert.equal(counter.isBlocked(key, 1), true);
  assert.equal(counter.isBlocked(key, 2000), false);
});

test("AttemptCounter reset clears a key", () => {
  const counter = new AttemptCounter(60_000, 1);
  const key = "room-c";
  counter.recordFailure(key, 0);
  assert.equal(counter.isBlocked(key, 0), true);
  counter.reset(key);
  assert.equal(counter.isBlocked(key, 0), false);
});

test("AttemptCounter sweep drops stale windows", () => {
  const counter = new AttemptCounter(1000, 5);
  counter.recordFailure("x", 0);
  counter.sweep(5000);
  assert.equal(counter.size, 0);
});

test("StrikeCounter trips after maxStrikes", () => {
  const strikes = new StrikeCounter(3);
  assert.equal(strikes.strike(), false);
  assert.equal(strikes.strike(), false);
  assert.equal(strikes.strike(), true);
});
