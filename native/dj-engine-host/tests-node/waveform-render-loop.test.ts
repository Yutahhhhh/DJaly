import test from "node:test";
import assert from "node:assert/strict";
import { createWaveformRenderLoop } from "../../../src/components/play/waveform-render-loop.ts";

function fixture() {
  const callbacks = new Map<number, FrameRequestCallback>();
  let next = 0, paints = 0, playing = false;
  const loop = createWaveformRenderLoop(() => paints++, () => playing,
    (callback) => { callbacks.set(++next, callback); return next; },
    (id) => { callbacks.delete(id); });
  return { loop, callbacks, paints: () => paints, play: (value: boolean) => { playing = value; },
    frame() { const batch = [...callbacks.values()]; callbacks.clear(); for (const callback of batch) callback(0); } };
}

test("resize and 50Hz telemetry bursts never paint synchronously or queue duplicate frames", () => {
  const f = fixture();
  for (let i = 0; i < 1000; i++) f.loop.invalidate();
  assert.equal(f.paints(), 0);
  assert.equal(f.callbacks.size, 1);
  f.frame();
  assert.equal(f.paints(), 1);
  assert.equal(f.callbacks.size, 0);
});

test("playback stays continuous through repeated resize bursts and sleeps after pause", () => {
  const f = fixture(); f.play(true); f.loop.invalidate();
  for (let frame = 0; frame < 120; frame++) {
    for (let resize = 0; resize < 20; resize++) f.loop.invalidate();
    assert.equal(f.callbacks.size, 1); f.frame();
  }
  assert.equal(f.paints(), 120);
  f.play(false); f.frame();
  assert.equal(f.callbacks.size, 0);
  f.loop.invalidate(); f.frame(); // paused seek/zoom still paints
  assert.equal(f.paints(), 122);
});

test("unmount cancels queued work and stale callbacks cannot restart the loop", () => {
  const f = fixture(); f.play(true); f.loop.invalidate();
  const stale = [...f.callbacks.values()][0];
  f.loop.dispose(); f.loop.invalidate(); stale(0);
  assert.equal(f.paints(), 0); assert.equal(f.callbacks.size, 0);
});
