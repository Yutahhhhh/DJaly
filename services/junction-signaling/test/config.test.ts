import { test } from "node:test";
import assert from "node:assert/strict";
import { loadConfig } from "../src/config.js";

test("config rejects oversized frames and long-lived or incomplete TURN settings", () => {
  assert.throws(() => loadConfig({ MAX_FRAME_BYTES: "65537" }));
  assert.throws(() => loadConfig({ TURN_URLS: "https://example.invalid" }));
  assert.throws(() => loadConfig({ TURN_URLS: "turn:example.invalid:3478" }));
  assert.throws(() => loadConfig({ TURN_TTL_SECONDS: "3601" }));
  assert.throws(() => loadConfig({ PORT: "65536" }));
  assert.equal(loadConfig({}).maxRooms, 1024);
});
