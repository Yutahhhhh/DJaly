// Held gesture state and the BEAT FX mix stream. Both are about what the
// runtime keeps between MIDI messages: a knob must not queue one engine round
// trip per CC, and a gesture started on one track must not be applied to the
// next one.
import test from "node:test";
import assert from "node:assert/strict";
import { Ddj1000Runtime } from "../../../src/services/midi/ddj1000-runtime.ts";
import type { MidiAction } from "../../../src/services/midi/ddj1000.ts";
import { Ddj1000Decoder, ddj1000Feedback } from "../../../src/services/midi/ddj1000.ts";
import { selectPads, getPadSelection, padSelectionFeedback, PAD_MODE_NOTES } from "../../../src/services/midi/pad-state.ts";
import type { DjEngineClient } from "../../../src/services/dj-engine/client.ts";
import type { EngineSnapshot } from "../../../src/types/dj-engine.ts";

/** Lets every queued promise chain run to completion. */
const settle = async () => { for (let n = 0; n < 8; n++) await new Promise(resolve => setTimeout(resolve, 0)); };

test("MIDI BPM feedback uses analyzed BPM times tempo just like the desktop", () => {
  const f=fixture([]);
  try {
    f.snapshot.decks.A.track!.bpm=120;
    f.snapshot.decks.A.rate=1.1;
    f.snapshot.decks.A.effectiveBpm=95;
    const bytes=ddj1000Feedback(f.snapshot);
    const msb=bytes.find(m=>m[0]===0xb0 && m[1]===0x15)![2];
    const lsb=bytes.find(m=>m[0]===0xb0 && m[1]===0x35)![2];
    assert.equal((msb<<7)|lsb,1320);
  } finally {f.runtime.dispose();}
});

test("physical page keys preserve the screen-selected mode and select two absolute pages", () => {
  const { runtime } = fixture([]);
  try {
    selectPads("A", 5, 0, true);
    for (let n = 0; n < 3; n++) runtime.dispatch({control:"padPage",deck:"A",mode:0,value:1,pressed:true});
    assert.deepEqual(getPadSelection("A"), {mode:5,page:1,software:true});
    runtime.dispatch({control:"padPage",deck:"A",mode:0,value:-1,pressed:true});
    assert.deepEqual(getPadSelection("A"), {mode:5,page:0,software:true});
  } finally { runtime.dispose(); }
});

function fixture(capabilities: string[]) {
  for (const deck of ["A","B","C","D"] as const) selectPads(deck,0);
  const calls: { name: string; args: unknown[] }[] = [], errors: string[] = [];
  let session = "one", generation = 0;
  const snapshot = {
    engine: { capabilities },
    decks: Object.fromEntries(["A", "B", "C", "D"].map(deck => [deck, {
      track: { trackId: deck, durationMs: 20000 }, status: "paused", positionMs: 1000,
      rate: 1, hotCues: Array(16).fill(null), loopRegion: null,
    }])),
    mixer: { channels: Object.fromEntries(["A", "B", "C", "D"].map(deck => [deck, { pfl: false }])) },
  } as unknown as EngineSnapshot;
  const client = new Proxy({}, { get: (_, name: string) => {
    if (name === "getDeckGeneration") return () => generation;
    if (name === "getState") return () => ({ snapshot });
    if (name === "refreshSnapshot") return async () => snapshot;
    if (name === "getSessionId") return () => session;
    return async (...args: unknown[]) => { calls.push({ name, args }); return {}; };
  } }) as DjEngineClient;
  const actions = { activate: () => {}, library: () => {}, hotcue: async () => {}, cuePoints: { A: 0, B: 0, C: 0, D: 0 }, error: (e: string) => errors.push(e) };
  const runtime = new Ddj1000Runtime(client, () => actions);
  return { runtime, calls, errors, snapshot, loadAnotherTrack: () => { generation++; } };
}

test("the BEAT FX mix knob coalesces instead of queueing one request per CC", async () => {
  const { runtime, calls } = fixture(["mixer.beatfx"]);
  try {
    // A single sweep of the knob; the DJ has already passed every value but the last.
    for (let n = 1; n <= 20; n++) runtime.dispatch({ control: "fxMix", value: n / 20 } as MidiAction);
    await settle();
    const sends = calls.filter(call => call.name === "send" && call.args[0] === "mixer.beatfx.set");
    assert.ok(sends.length > 0, "the knob must reach the engine at all");
    assert.ok(sends.length <= 3, `a 20-message sweep must not become 20 requests: ${sends.length}`);
    // Whatever is dropped, the position the knob was left at must be the one applied.
    assert.equal((sends.at(-1)!.args[1] as { mix: number }).mix, 1);
  } finally { runtime.dispose(); }
});

test("all eight physical pad modes switch unloaded decks and publish the selected lamp", () => {
  const {runtime,snapshot}=fixture([]), decoder=new Ddj1000Decoder();
  snapshot.decks.A.track=null;
  try {
    for(let mode=0;mode<8;mode++) {
      for(const action of decoder.feed([0x90,PAD_MODE_NOTES[mode],127,0x90,PAD_MODE_NOTES[mode],0])) runtime.dispatch(action);
      assert.equal(getPadSelection("A").mode,mode);
      const lamps=padSelectionFeedback().filter(([s,k])=>s===0x90 && (PAD_MODE_NOTES as readonly number[]).includes(k));
      assert.deepEqual(lamps.filter(([, ,v])=>v===127),[[0x90,PAD_MODE_NOTES[mode],127]]);
    }
  } finally {runtime.dispose();}
});

test("a screen-selected PAD FX works with old firmware notes and releases after switching modes", async () => {
  const {runtime,calls}=fixture(["mixer.fx"]),decoder=new Ddj1000Decoder();
  try {
    selectPads("A",5,0,true);
    for(const action of decoder.feed([0x97,0x00,127])) runtime.dispatch(action);
    await settle();
    assert.ok(calls.some(c=>c.name==="setFx" && c.args[2]===true));
    selectPads("A",0,0,true);
    for(const action of decoder.feed([0x97,0x00,0])) runtime.dispatch(action);
    await settle();
    assert.ok(calls.some(c=>c.name==="setFx" && c.args[2]===false),"note-off must release the original effect, not clear a hot cue");
  } finally {runtime.dispose();}
});

test("release FX can be pressed again after a depth change and each note-off reaches the engine", async () => {
  const {runtime,calls}=fixture(["mixer.beatfx","mixer.beatfx.release"]),decoder=new Ddj1000Decoder();
  try {
    for(const bytes of [[0x94,0x43,127],[0xb4,2,32,0xb4,34,0],[0x94,0x43,0],[0x94,0x43,127],[0x94,0x43,0]]) {
      for(const action of decoder.feed(bytes)) runtime.dispatch(action);
      await settle();
    }
    assert.deepEqual(calls.filter(c=>c.name==="send" && c.args[0]==="mixer.beatfx.set" && "release" in (c.args[1] as object)).map(c=>(c.args[1] as {release:boolean}).release),[true,false,true,false]);
  } finally {runtime.dispose();}
});

test("fine jog sensitivity preserves cumulative motion and exact reverse travel", async () => {
  const {runtime,calls}=fixture([]);
  runtime.jogSensitivity=0.5;
  try {
    runtime.dispatch({control:"touch",deck:"A",value:127,pressed:true});
    for(const value of [4,4,-8]) runtime.dispatch({control:"jog",deck:"A",value});
    runtime.dispatch({control:"touch",deck:"A",value:0,pressed:false});
    await settle();
    assert.deepEqual(calls.filter(c=>c.name==="scratch").map(c=>[c.args[1],c.args[2]]),[["begin",0],["move",2],["move",4],["move",0],["end",0]]);
  } finally {runtime.dispose();}
});

test("an invalid BEAT FX index does not leave a valid effect permanently off", async () => {
  const {runtime,calls,snapshot}=fixture(["mixer.beatfx"]);
  snapshot.mixer.beatFx={effect:"echo",enabled:true,target:"A",mix:0.5,beats:0.5};
  try {
    runtime.dispatch({control:"fxSelect",value:14,pressed:true});
    await settle();
    snapshot.mixer.beatFx.enabled=false;
    runtime.dispatch({control:"fxMix",value:0.3});
    runtime.dispatch({control:"fxSelect",value:1,pressed:true});
    await settle();
    const parameters=calls.filter(c=>c.name==="send" && c.args[0]==="mixer.beatfx.set").map(c=>c.args[1]);
    assert.deepEqual(parameters.at(-1),{effect:"echo",enabled:true});
  } finally {runtime.dispose();}
});

test("all fourteen official BEAT FX selector messages reach the engine without disabling FX", async () => {
  const {runtime,calls,errors}=fixture(["mixer.beatfx"]), decoder=new Ddj1000Decoder();
  const expected=["lowcutecho","echo","mtdelay","spiral","reverb","tremolo","enigmajet","flanger","phaser","pitchshift","sliproll","roll","mobiussaw","mobiustri"];
  try {
    for(let index=0;index<14;index++) {
      for(const action of decoder.feed([0x94,0x20+index,127,0x94,0x20+index,0])) runtime.dispatch(action);
    }
    await settle();
    const params=calls.filter(c=>c.name==="send" && c.args[0]==="mixer.beatfx.set").map(c=>c.args[1]);
    assert.deepEqual(params,expected.map(effect=>({effect})));
    assert.deepEqual(errors,[]);
    for(const action of decoder.feed([0x94,0x47,127,0x94,0x47,0])) runtime.dispatch(action);
    await settle();
    assert.deepEqual(calls.at(-1)?.args,["mixer.beatfx.set",{toggle:true}]);
  } finally {runtime.dispose();}
});

test("SHIFT BEAT TAP measures input time and AUTO restores source timing", async (t) => {
  const {runtime,calls}=fixture(["mixer.beatfx"]), decoder=new Ddj1000Decoder();
  let now=1000;
  t.mock.method(performance,"now",()=>now);
  try {
    for(let tap=0;tap<3;tap++) {
      for(const action of decoder.feed([0x94,0x6b,127,0x94,0x6b,0])) runtime.dispatch(action);
      now+=500;
    }
    await settle();
    const params=calls.filter(c=>c.name==="send").map(c=>c.args[1]);
    assert.deepEqual(params,[{bpm:120},{bpm:120}]);
    for(const action of decoder.feed([0x94,0x66,127,0x94,0x66,0])) runtime.dispatch(action);
    await settle();
    assert.deepEqual(calls.at(-1)?.args,["mixer.beatfx.set",{auto:true}]);
  } finally {runtime.dispose();}
});

test("a mix value arriving mid-flight is still applied after the in-flight request", async () => {
  const { runtime, calls } = fixture(["mixer.beatfx"]);
  try {
    runtime.dispatch({ control: "fxMix", value: 0.2 } as MidiAction);
    await Promise.resolve();
    runtime.dispatch({ control: "fxMix", value: 0.9 } as MidiAction);
    await settle();
    const sends = calls.filter(call => call.name === "send" && call.args[0] === "mixer.beatfx.set");
    assert.equal((sends.at(-1)!.args[1] as { mix: number }).mix, 0.9, "the newest position must win");
  } finally { runtime.dispose(); }
});

test("loop IN/OUT adjust mode does not survive a track change", async () => {
  const { runtime, calls, snapshot, loadAnotherTrack } = fixture([]);
  try {
    snapshot.decks.A.loopRegion = { startMs: 1000, endMs: 2000, enabled: true };
    runtime.dispatch({ control: "loopInAdjust", deck: "A", value: 1, pressed: true } as MidiAction);
    // While the gesture is live the platter edits the loop rather than scratching.
    runtime.dispatch({ control: "jog", deck: "A", value: 4, surface: "platter" } as MidiAction);
    await settle();
    assert.ok(calls.some(call => call.name === "setLoop"), "adjust mode must edit the loop while it is live");

    calls.length = 0;
    loadAnotherTrack();
    runtime.dispatch({ control: "jog", deck: "A", value: 4, surface: "platter" } as MidiAction);
    await settle();
    assert.ok(!calls.some(call => call.name === "setLoop"), `a new track must not inherit adjust mode: ${JSON.stringify(calls)}`);
  } finally { runtime.dispose(); }
});

test("a stored loop IN point is discarded when the track changes before loop OUT", async () => {
  const { runtime, calls, snapshot, loadAnotherTrack } = fixture([]);
  try {
    snapshot.decks.A.loopRegion = null;
    runtime.dispatch({ control: "loopIn", deck: "A", value: 1, pressed: true } as MidiAction);
    await settle();
    calls.length = 0;

    loadAnotherTrack();
    snapshot.decks.A.positionMs = 5000;
    runtime.dispatch({ control: "loopOut", deck: "A", value: 1, pressed: true } as MidiAction);
    await settle();
    assert.ok(!calls.some(call => call.name === "setLoop"), `the previous track's IN point must not build a loop: ${JSON.stringify(calls)}`);
  } finally { runtime.dispose(); }
});


test("playing jog bends audio without writing tempo; held side motion stays in scratch", async () => {
  const f = fixture(["deck.pitchbend"]);
  f.snapshot.decks.A.status = "playing";
  try {
    f.runtime.dispatch({control:"nudge",deck:"A",value:-50});
    await settle();
    assert.equal(f.calls.filter(c=>c.name==="setTempo").length,0);
    assert.deepEqual(f.calls.find(c=>c.name==="pitchbend")?.args,["A",-.1]);
    f.runtime.dispatch({control:"touch",deck:"A",value:127,pressed:true});
    f.runtime.dispatch({control:"nudge",deck:"A",value:-20});
    await settle();
    assert.equal(f.calls.filter(c=>c.name==="pitchbend").length,1);
    assert(f.calls.some(c=>c.name==="scratch" && c.args[1]==="move" && Number(c.args[2])<0));
  } finally {f.runtime.dispose();}
});

test("moving platter sends no duplicate stop-position heartbeats", async () => {
  const f=fixture(["deck.pitchbend"]);
  try {
    f.runtime.dispatch({control:"touch",deck:"A",value:127,pressed:true});
    for(let i=0;i<10;i++) {
      f.runtime.dispatch({control:"jog",deck:"A",value:-40});
      await new Promise(resolve=>setTimeout(resolve,50));
    }
    assert.equal(f.calls.filter(c=>c.name==="scratch" && c.args[1]==="move").length,10,
      "Motion must not be interrupted by duplicate positions interpreted as a stationary hand");
    const before=f.calls.length;
    await new Promise(resolve=>setTimeout(resolve,450));
    assert(f.calls.slice(before).some(c=>c.name==="scratch" && c.args[1]==="move"),
      "Stationary held platter must still keep its watchdog alive");
  } finally {f.runtime.dispose();}
});

test("fast reverse rotation survives touch release until rotation packets stop", async () => {
  const f=fixture(["deck.pitchbend"]);
  f.snapshot.decks.A.status="playing";
  f.runtime.jogSensitivity=1;
  const send=(control: string,value: number,pressed?: boolean)=>f.runtime.dispatch({deck:"A",control,value,pressed});
  try {
    send("touch",127,true);
    await new Promise(resolve=>setTimeout(resolve,20)); send("jog",-40);
    await new Promise(resolve=>setTimeout(resolve,20)); send("jog",-40);
    send("touch",0,false);
    await new Promise(resolve=>setTimeout(resolve,35)); send("nudge",-35);
    await settle();
    assert.equal(f.calls.filter(c=>c.name==="scratch" && c.args[1]==="end").length,0);
    assert.equal(f.calls.filter(c=>c.name==="pitchbend" || c.name==="setTempo").length,0);
    send("touch",127,true);
    await settle();
    assert.equal(f.calls.filter(c=>c.name==="scratch" && c.args[1]==="begin").length,1,
      "Restored touch must keep the same gesture and position origin");
    send("touch",0,false);
    await new Promise(resolve=>setTimeout(resolve,100));
    assert.equal(f.calls.filter(c=>c.name==="scratch" && c.args[1]==="end").length,1,
      "No new rotation must release without inventing an inertial spin");
  } finally {f.runtime.dispose();}
});
