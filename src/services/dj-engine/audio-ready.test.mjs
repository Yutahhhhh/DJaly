import test from "node:test";
import assert from "node:assert/strict";
import { ensureAudioReady, parseOutputRouting } from "./audio-ready.ts";

const snapshot = applied => ({ audio: { applied, reason: applied ? null : "Device unavailable" }, decks: {}, recording: { active: false } });
test("failed live host is recreated once for concurrent track loads", async () => {
  let state = snapshot(false), stops = 0, starts = 0;
  const client = {
    getState: () => ({ snapshot: state }), refreshSnapshot: async () => state,
    stop: async () => { stops++; }, start: async (device) => { assert.equal(device,"Speakers"); starts++; return {running: true}; },
    connect: async () => { state = snapshot(true); },
  };
  await Promise.all([ensureAudioReady(client,"Speakers"),ensureAudioReady(client,"Speakers")]);
  assert.equal(stops, 1); assert.equal(starts, 1);
  await ensureAudioReady(client,"Speakers");
  assert.equal(starts, 1);
});
test("recording is never interrupted to recover an output", async () => {
  const state = snapshot(false); state.recording.active = true;
  const client = { refreshSnapshot: async () => state, stop: async () => assert.fail("must not stop") };
  await assert.rejects(ensureAudioReady(client), /Device unavailable/);
});
test("failed recovery reports native reason and does not choose another output", async () => {
  let starts=0;
  const client = { refreshSnapshot: async () => snapshot(false), stop: async()=>{}, start: async()=>{starts++;return {running:true};}, connect: async()=>{} };
  await assert.rejects(ensureAudioReady(client), /Device unavailable/);
  assert.equal(starts,1);
});
test("saved output routing validates pairs and channel overlap", () => {
  const saved={deviceId:"Speakers",routing:{masterChannels:[0,1],pflChannels:[2,3]}};
  assert.deepEqual(parseOutputRouting(JSON.stringify(saved)),saved);
  saved.routing.pflChannels=[1,2];
  assert.equal(parseOutputRouting(JSON.stringify(saved)),null);
  assert.equal(parseOutputRouting("null"),null);
});
