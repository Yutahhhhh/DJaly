import test from "node:test";
import assert from "node:assert/strict";
import { jogWaveform, jogFrame, isJogScreenMidi } from "../../../src/services/midi/ddj1000-display.ts";
import type { DeckState } from "../../../src/types/dj-engine.ts";
test("waveform fits 600 columns, bounds malformed peaks and keeps transients", () => {
  const input = Array(1200).fill(0); input[601]=1; input[100]=NaN;
  const wave = jogWaveform(input);
  assert.equal(wave.length,4201); assert.equal(wave[0],128);
  assert.equal(wave[1+300*7+4],31);
  assert.equal(wave[1+50*7+4],0);
  assert.ok(wave.every(b=>Number.isInteger(b)&&b>=0&&b<=255));
});
test("MIDI screen overlay is suppressed without suppressing buttons, pads or mixer", () => {
  for (let ch=0;ch<4;ch++) {
    assert.ok(isJogScreenMidi([0x90+ch,0x5d,0]));
    assert.ok(isJogScreenMidi([0xb0+ch,0x35,127]));
    assert.ok(!isJogScreenMidi([0x90+ch,0x0b,127]));
    assert.ok(!isJogScreenMidi([0xb0+ch,2,127]));
  }
  assert.ok(!isJogScreenMidi([0x97,0x35,127]));
  assert.ok(!isJogScreenMidi([0xb4,2,127]));
});
test("unloaded frames drop identity and variable grids are bounded", () => {
  assert.equal(jogFrame(undefined,"old").token,"");
  const deck = {deck:"B",track:{durationMs:3000000,bpm:120,beatTimesMs:Array.from({length:5000},(_,i)=>i*500)},positionMs:61000,rate:1,status:"playing",syncLeader:"B",hotCues:[1000,null]} as DeckState;
  const frame=jogFrame(deck,"session:B:track");
  assert.equal(frame.beats.length,2000);
  assert.equal(frame.beats.at(-1),2499500);
  assert.ok(frame.master && frame.playing);
  assert.deepEqual(frame.cues,[1000,null]);
  assert.equal(jogFrame({...deck,scratching:true},"same").playing,false);
});

test("jog BPM follows analyzed tempo and slider rather than scratch-position local BPM", () => {
  const deck={track:{bpm:120,durationMs:20000},rate:1.1,effectiveBpm:137,hotCues:[]} as unknown as DeckState;
  assert.equal(jogFrame(deck,"track").bpm,132);
  assert.equal(jogFrame({...deck,effectiveBpm:95,scratching:true},"track").bpm,132);
  assert.equal(jogFrame({...deck,track:{...deck.track!,bpm:null},effectiveBpm:95},"track").bpm,95);
});
