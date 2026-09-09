import test from "node:test";
import assert from "node:assert/strict";
import { DEFAULT_MICROPHONE, microphoneCommandParams, parseMicrophoneSettings } from "../../../src/services/dj-engine/audio-settings.ts";

test("snapshot microphone meters/status never become unsupported command fields", () => {
  const snapshot = { ...DEFAULT_MICROPHONE, deviceId: "USB Mic", available: true, applied: true, level: 0.4, reason: "" };
  assert.deepEqual(microphoneCommandParams(snapshot), { microphone: { ...DEFAULT_MICROPHONE, deviceId: "USB Mic" } });
  assert.deepEqual(microphoneCommandParams({ enabled: false }), { microphone: { enabled: false } });
});
test("corrupted persisted routing does not activate a microphone", () => {
  for (const raw of ["null", "{", "{}", JSON.stringify({ ...DEFAULT_MICROPHONE, gain: 100 }), JSON.stringify({ ...DEFAULT_MICROPHONE, channel: -1 }), JSON.stringify({ ...DEFAULT_MICROPHONE, enabled: "false" })]) {
    assert.equal(parseMicrophoneSettings(raw), null);
  }
  assert.deepEqual(parseMicrophoneSettings(JSON.stringify(DEFAULT_MICROPHONE)), DEFAULT_MICROPHONE);
});
