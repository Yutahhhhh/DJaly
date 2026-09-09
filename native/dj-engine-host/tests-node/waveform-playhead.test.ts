import test from "node:test";
import assert from "node:assert/strict";
import { waveformPlayhead } from "../../../src/components/play/waveform-playhead.ts";

test("held-pointer preview advances with audio and tempo instead of freezing at the last move", () => {
  const telemetry = { position: 1000, receivedAt: 0 };
  const preview = { position: 5000, at: 10, until: 610 };
  assert.equal(waveformPlayhead(telemetry, preview, 110, true, 1.2, 10000), 5120);
  assert.equal(waveformPlayhead(telemetry, preview, 210, true, 1.2, 10000), 5240);
  assert.equal(waveformPlayhead(telemetry, preview, 210, false, 1.2, 10000), 5000);
});

test("expired preview follows real engine position; absent telemetry cannot drift forever", () => {
  const telemetry = { position: 7000, receivedAt: 600 };
  const preview = { position: 5000, at: 10, until: 610 };
  assert.equal(waveformPlayhead(telemetry, preview, 650, true, 1, 10000), 7050);
  assert.equal(waveformPlayhead(telemetry, null, 5000, true, 1, 10000), 7200);
  assert.equal(waveformPlayhead(telemetry, null, 650, false, 1, 10000), 7000);
});

test("predicted audio playhead stays inside the loaded track", () => {
  assert.equal(waveformPlayhead({ position: 9990, receivedAt: 0 }, null, 100, true, 1, 10000), 10000);
  assert.equal(waveformPlayhead({ position: 0, receivedAt: 100 }, null, 0, true, 1, 10000), 0);
});

test("negative audio transport needs no pre-roll mode and crosses zero at the deck tempo", () => {
  assert.equal(waveformPlayhead({ position: -2000, receivedAt: 0 }, null, 100, true, 1, 10000), -1900);
  assert.equal(waveformPlayhead({ position: -50, receivedAt: 0 }, null, 100, true, 1.2, 10000), 70);
  assert.equal(waveformPlayhead({ position: -2000, receivedAt: 0 }, null, 0, false, 1, 10000), -2000);
  // Overview may explicitly constrain its viewport, not the transport.
  assert.equal(waveformPlayhead({ position: -2000, receivedAt: 0 }, null, 0, false, 1, 10000, 0), 0);
});
