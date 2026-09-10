import test from "node:test";
import assert from "node:assert/strict";
import { GenericMidiDecoder } from "./generic-midi.ts";

const profile = { schemaVersion: 1, adapterId: "generic-midi", bindings: [
  { id:"play", input:{kind:"note",channel:0,number:11}, encoding:"button", actionId:"deck.play", deck:"A", trigger:"press" },
  { id:"browse", input:{kind:"cc",channel:6,number:64}, encoding:"relative-twos-complement", actionId:"library.browse" },
  { id:"fader", input:{kind:"cc14",channel:0,number:19}, encoding:"absolute", actionId:"mixer.channel_fader", deck:"A" },
  { id:"pitch", input:{kind:"pitchbend",channel:2,number:0}, encoding:"absolute", actionId:"deck.tempo", deck:"B" },
] };
test("generic mapping decodes press once and signed relative CC", () => {
  const decoder = new GenericMidiDecoder(profile);
  assert.deepEqual(decoder.feed([0x90,11,127,0x90,11,127]), [{control:"play",deck:"A",slot:undefined,value:127,pressed:true}]);
  assert.equal(decoder.feed([0x80,11,0]).length, 0);
  assert.equal(decoder.feed([0xb6,64,127])[0].value, -1);
  assert.equal(decoder.feed([0xb0,19,64,0xb0,51,0])[0].value, 8192 / 16383);
  assert.equal(decoder.feed([0xe2,127,127])[0].value, 1);
});

test("split messages, running status and interleaved realtime are preserved", () => {
  const decoder = new GenericMidiDecoder(profile);
  assert.deepEqual(decoder.feed([0x90, 11]), []);
  assert.equal(decoder.feed([0xf8, 127])[0].control, "play");
  decoder.feed([11, 0]);
  assert.equal(decoder.feed([11, 127])[0].control, "play");
  decoder.reset();
  assert.deepEqual(decoder.feed([127]), []);
});

test("sysex and short channel messages do not corrupt following controls", () => {
  const decoder = new GenericMidiDecoder(profile);
  const actions = decoder.feed([0xf0,1,2,0xf8,3,0xf7,0xc0,42,0x90,11,127]);
  assert.equal(actions.length, 1);
  assert.equal(actions[0].control, "play");
});

test("DDJ-400 uses its own bindings and offset jog encoding", async () => {
  const { DDJ400_PROFILE } = await import("./ddj400.ts");
  const decoder = new GenericMidiDecoder(DDJ400_PROFILE);
  assert.equal(decoder.feed([0xb0,34,65])[0].value, 1);
  assert.equal(decoder.feed([0xb0,34,63])[0].value, -1);
  assert.equal(decoder.feed([0x96,71,127])[0].deck, "B");
  const mapped = structuredClone(DDJ400_PROFILE);
  mapped.bindings.find(b => b.id === "play-a").input.number = 40;
  const custom = new GenericMidiDecoder(mapped);
  assert.equal(custom.feed([0x90,11,127]).length, 0);
  assert.equal(custom.feed([0x90,40,127])[0].control, "play");
});
