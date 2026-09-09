import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { Ddj1000Decoder, ddj1000Feedback } from "../../../src/services/midi/ddj1000.ts";
import { Ddj1000Runtime } from "../../../src/services/midi/ddj1000-runtime.ts";
import type { DjEngineClient } from "../../../src/services/dj-engine/client.ts";
import type { EngineSnapshot } from "../../../src/types/dj-engine.ts";

const official = JSON.parse(readFileSync(new URL("./fixtures/ddj1000-midi-map.json", import.meta.url), "utf8")) as {
  group: string; control: string; shift: string; condition: string; type: string; status_in: string; data1_in: string;
}[];
test("official table excludes the four phantom deck notes on all decks", () => {
  assert.equal(official.length, 453);
  for (let ch = 0; ch < 4; ch++) for (const key of [0x12, 0x13, 0x3a, 0x3c]) {
    assert.ok(!official.some(row => row.group === "DECK" && row.type === "NOTE" && parseInt(row.data1_in, 16) === key));
    assert.deepEqual(new Ddj1000Decoder().feed([0x90 + ch, key, 127, key, 0]), []);
  }
});
test("all six official jog CCs preserve surface, modifiers and signed movement", () => {
  const rows = official.filter(row => row.group === "DECK" && row.control.startsWith("JOG") && row.type === "CC");
  assert.equal(rows.length, 6);
  const expected = new Map([
    [0x22, ["jog", "platter", true, undefined, undefined]],
    [0x23, ["jog", "platter", false, undefined, undefined]],
    [0x21, ["nudge", "side", undefined, undefined, undefined]],
    [0x26, ["searchJog", "side", undefined, true, undefined]],
    [0x29, ["searchJog", "platter", undefined, undefined, true]],
    [0x1f, ["jog", "platter", undefined, true, undefined]],
  ]);
  for (const row of rows) for (let ch = 0; ch < 4; ch++) for (const value of [63, 64, 65]) {
    const key = parseInt(row.data1_in, 16);
    const [action] = new Ddj1000Decoder().feed([0xb0 + ch, key, value]);
    assert.equal(action.deck, ["A", "B", "C", "D"][ch]);
    assert.equal(action.value, value - 64);
    assert.deepEqual([action.control, action.surface, action.vinyl, action.shift, action.search], expected.get(key));
  }
  // The same CC numbers on the mixer/FX channels are 14-bit controls.
  assert.equal(new Ddj1000Decoder().feed([0xb4, 2, 64, 34, 0])[0].control, "fxMix");
  assert.equal(new Ddj1000Decoder().feed([0xb6, 31, 64, 63, 0])[0].control, "crossfader");
});
test("both pad pages follow the formula on all eight pad channels", () => {
  for (let channel = 7; channel <= 14; channel++) for (let note = 0; note < 128; note++) {
    const [action] = new Ddj1000Decoder().feed([0x90 + channel, note, 127]);
    assert.equal(action.control, ["hotcue", "padFx", "beatJumpPad", "sampler", "keyboard", "padFx", "beatLoopPad", "keyShift"][note >> 4]);
    assert.equal(action.slot, ((note >> 3) & 1) * 8 + (note & 7));
    assert.equal(action.shift, channel % 2 === 0);
    assert.equal(action.deck, ["A", "B", "C", "D"][Math.floor((channel - 7) / 2)]);
  }
});

test("four deck note-on/off routing, press debounce, and shift pads", () => {
  const d = new Ddj1000Decoder();
  assert.deepEqual(d.feed([0x92, 0x0b, 127]).map(a => [a.control, a.deck, a.pressed]), [["play", "C", true]]);
  assert.equal(d.feed([0x92, 0x0b, 127]).length, 0);
  assert.equal(d.feed([0x82, 0x0b, 64])[0].pressed, false);
  assert.deepEqual(d.feed([0x9e, 7, 127]).map(a => [a.control, a.deck, a.slot, a.shift]), [["hotcue", "D", 7, true]]);
});
test("14-bit CC pairs are channel-local, exact, and never reuse consumed MSB", () => {
  const d = new Ddj1000Decoder();
  assert.equal(d.feed([0xb0, 0x13, 127, 0xb1, 0x13, 0]).length, 0);
  assert.deepEqual(d.feed([0xb0, 0x33, 127, 0xb1, 0x33, 0]).map(a => [a.deck, a.control, a.value]), [["A", "gain", 1], ["B", "gain", 0]]);
  assert.equal(d.feed([0xb0, 0x33, 0]).length, 0);
  assert.equal(d.feed([0xb6, 0x1f, 127, 0x3f, 127])[0].value, 1);
});
test("fragmented running status tolerates realtime and ignores SysEx payload", () => {
  const d = new Ddj1000Decoder();
  assert.deepEqual(d.feed([0x90, 11]), []);
  assert.equal(d.feed([0xf8, 127, 11, 0]).length, 2);
  assert.deepEqual(d.feed([0xf0, 0x90, 11, 127, 0xf7, 11, 127]), []);
  assert.equal(d.feed([0x90, 11, 127])[0].control, "play");
});
test("jog and encoder signed values do not collide with hi-res LSB", () => {
  const d = new Ddj1000Decoder();
  assert.deepEqual(d.feed([0xb0, 0x22, 63, 0x22, 65]).map(a => a.value), [-1, 1]);
  assert.equal(d.feed([0xb6, 0x40, 127])[0].value, -1);
  assert.equal(d.feed([0xb0, 0, 64, 0x20, 0])[0].control, "tempo");
});
test("reset drops partial controls and releases note debounce", () => {
  const d = new Ddj1000Decoder(); d.feed([0xb0, 19, 127, 0x90, 11, 127]); d.reset();
  assert.equal(d.feed([0xb0, 51, 127]).length, 0);
  assert.equal(d.feed([0x90, 11, 127]).length, 1);
});
function fixture() {
  const calls: { name: string; args: unknown[] }[] = [], errors: string[] = [];
  let session = "one", generation = 0;
  const snapshot = { decks: Object.fromEntries(["A", "B", "C", "D"].map(deck => [deck, { track: { trackId: deck, durationMs: 20000 }, status: "paused", positionMs: 1000, rate: 1, hotCues: Array(8).fill(null), loopRegion: null }])), mixer: { channels: Object.fromEntries(["A", "B", "C", "D"].map(deck => [deck, { pfl: false }])) } } as unknown as EngineSnapshot;
  const client = new Proxy({}, { get: (_, name: string) => {
    if (name === "getDeckGeneration") return () => generation;
    if (name === "getState") return () => ({ snapshot });
    if (name === "refreshSnapshot") return async () => snapshot;
    if (name === "getSessionId") return () => session;
    return async (...args: unknown[]) => {
      calls.push({ name, args });
      const deck = args[0] as "A";
      if (name === "play") snapshot.decks[deck].status = "playing";
      if (name === "pause") snapshot.decks[deck].status = "paused";
      if (name === "seek") snapshot.decks[deck].positionMs = args[1] as number;
    };
  } }) as DjEngineClient;
  const actions = { activate: () => {}, library: () => {}, hotcue: async () => {}, cuePoints: { A: 0, B: 0, C: 0, D: 0 }, error: (e: string) => errors.push(e) };
  const runtime = new Ddj1000Runtime(client, () => actions);
  return { runtime, calls, snapshot, errors, actions, reload: () => { generation++; }, changeSession: () => { session = "two"; } };
}
const flush = () => new Promise(resolve => setTimeout(resolve, 10));
test("rapid play presses serialize against acknowledged state", async () => {
  const f = fixture(); try {
    f.runtime.dispatch({ control: "play", deck: "A", value: 127, pressed: true });
    f.runtime.dispatch({ control: "play", deck: "A", value: 127, pressed: true });
    await flush(); assert.deepEqual(f.calls.map(c => c.name), ["play", "pause"]);
  } finally { f.runtime.dispose(); }
});
test("CUE audition returns on release; PLAY while held latches playback", async () => {
  const f = fixture(); f.actions.cuePoints.A = 1000; try {
    f.runtime.dispatch({ control: "cue", deck: "A", value: 127, pressed: true });
    f.runtime.dispatch({ control: "cue", deck: "A", value: 0, pressed: false });
    await flush(); assert.deepEqual(f.calls.map(c => c.name), ["play", "pause", "seek"]);
    f.calls.length = 0;
    for (const [control, pressed] of [["cue", true], ["play", true], ["cue", false]] as const) f.runtime.dispatch({ control, deck: "A", value: 127, pressed });
    await flush(); assert.deepEqual(f.calls.map(c => c.name), ["play"]);
  } finally { f.runtime.dispose(); }
});
test("queued commands cannot act on a replacement track or session", async () => {
  const f = fixture(); try {
    f.runtime.dispatch({ control: "play", deck: "A", value: 127, pressed: true }); f.changeSession();
    await flush(); assert.equal(f.calls.length, 0);
    f.runtime.dispatch({ control: "cue", deck: "A", value: 127, pressed: true }); f.snapshot.decks.A.track!.trackId = "replacement";
    await flush(); assert.equal(f.calls.length, 0);
  } finally { f.runtime.dispose(); }
});
test("disconnect ends a held scratch and prevents delayed queued actions", async () => {
  const f = fixture(); try {
    f.runtime.dispatch({ control: "touch", deck: "A", value: 127, pressed: true });
    f.runtime.dispatch({ control: "jog", deck: "A", value: 2 });
    f.runtime.dispatch({ control: "play", deck: "A", value: 127, pressed: true });
    f.runtime.reset(); await flush();
    assert.deepEqual(f.calls.map(c => [c.name, c.args[1]]), [["scratch", "begin"], ["scratch", "move"], ["scratch", "end"]]);
    assert.equal(f.calls[1].args[2], 3.6);
  } finally { f.runtime.dispose(); }
});
test("disconnect turns off a held pad FX", async () => {
  const f = fixture(); try {
    f.runtime.dispatch({ control: "padFx", deck: "A", value: 127, pressed: true, slot: 0 }); await flush();
    f.runtime.reset(); await flush();
    assert.deepEqual(f.calls.filter(c => c.name === "setFx").map(c => c.args[2]), [true, false]);
  } finally { f.runtime.dispose(); }
});
test("feedback has valid bytes and reflects engine changes on all decks", () => {
  const f = fixture(); try {
    f.snapshot.decks.C.status = "playing"; f.snapshot.decks.D.hotCues[7] = 42;
    const bytes = ddj1000Feedback(f.snapshot);
    assert.ok(bytes.every(m => m.length === 3 && m.slice(1).every(v => Number.isInteger(v) && v >= 0 && v <= 127)));
    assert.ok(bytes.some(m => m.join() === [0x92, 11, 127].join()));
    assert.ok(bytes.some(m => m.join() === [0x9d, 7, 127].join()));
    assert.ok(ddj1000Feedback(null).some(m => m.join() === [0x92, 11, 0].join()));
  } finally { f.runtime.dispose(); }
});
test("official display ranges clamp BPM/speed and identify sync master", () => {
  const f = fixture(); try {
    f.snapshot.decks.A.effectiveBpm = 1200;
    f.snapshot.decks.A.rate = 4;
    f.snapshot.decks.A.syncLeader = "A";
    const bytes = ddj1000Feedback(f.snapshot);
    for (const key of [0x15, 0x16]) {
      assert.deepEqual(bytes.find(m => m[0] === 0xb0 && m[1] === key), [0xb0, key, 0x4e]);
      assert.deepEqual(bytes.find(m => m[0] === 0xb0 && m[1] === key + 32), [0xb0, key + 32, 0x0f]);
    }
    assert.ok(bytes.some(m => m.join() === "144,89,127"));
    assert.ok(bytes.some(m => m.join() === "145,89,0"));
    assert.ok(bytes.length <= 256);
    // Undocumented meter output is deliberately preserved pending a visual test.
    for (let ch = 0; ch < 4; ch++) assert.ok(bytes.some(m => m[0] === 0xb0 + ch && m[1] === 2));
    assert.ok(!bytes.some(m => m[0] === 0xb4 && [2, 34].includes(m[1])));
  } finally { f.runtime.dispose(); }
});
test("VINYL OFF platter and SEARCH platter cannot continue a held scratch", async () => {
  for (const key of [0x23, 0x29]) {
    const f = fixture(); try {
      const decoder = new Ddj1000Decoder();
      for (const action of decoder.feed([0x90, 0x36, 127])) f.runtime.dispatch(action);
      await flush();
      for (const action of decoder.feed([0xb0, key, 65])) f.runtime.dispatch(action);
      await flush();
      const scratch = f.calls.filter(c => c.name === "scratch");
      assert.deepEqual(scratch.map(c => c.args[1]), ["begin", "end"]);
      assert.ok(f.calls.some(c => c.name === "seek"));
    } finally { f.runtime.dispose(); }
  }
});

test("reloading the same track invalidates queued controller commands", async () => {
  const f = fixture(); try {
    f.runtime.dispatch({ control: "play", deck: "A", value: 127, pressed: true }); f.reload();
    await flush(); assert.equal(f.calls.length, 0);
  } finally { f.runtime.dispose(); }
});
test("paused jog accumulates rapid motion before telemetry catches up", async () => {
  const f = fixture(); try {
    f.runtime.dispatch({ control: "nudge", deck: "A", value: 1 });
    f.runtime.dispatch({ control: "nudge", deck: "A", value: 1 });
    await flush(); assert.ok(Math.abs(Number(f.calls[1].args[1]) - 1003.6) < 0.001);
  } finally { f.runtime.dispose(); }
});

test("BEAT FX depth bursts coalesce to the last position", async () => {
  const f = fixture(); try {
    for (let i = 0; i <= 1000; i++) f.runtime.dispatch({ control: "fxMix", value: i / 1000 });
    await flush();
    const updates = f.calls.filter(c => c.name === "setFx");
    assert.equal(updates.length, 1); assert.equal(updates[0].args[3], 1);
  } finally { f.runtime.dispose(); }
});
test("hardware tempo range uses the same default and cycle as the screen", () => {
  const f = fixture(); try {
    f.runtime.dispatch({ control: "tempo", deck: "A", value: 1 });
    f.runtime.dispatch({ control: "tempoRange", deck: "A", value: 127, pressed: true });
    f.runtime.dispatch({ control: "tempo", deck: "A", value: 1 });
    assert.deepEqual(f.calls.filter(c => c.name === "setTempo").map(c => c.args[1]), [1.16, 1.75]);
  } finally { f.runtime.dispose(); }
});

test("CUE while paused away from the cue sets the cue without starting audio", async () => {
  const f = fixture(); try {
    f.runtime.dispatch({ control: "cue", deck: "A", value: 127, pressed: true });
    f.runtime.dispatch({ control: "cue", deck: "A", value: 0, pressed: false });
    await flush(); assert.equal(f.actions.cuePoints.A, 1000); assert.equal(f.calls.length, 0);
  } finally { f.runtime.dispose(); }
});
