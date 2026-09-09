import { test } from "node:test";
import assert from "node:assert/strict";
import {
  parseClientFrame,
  sanitizeDisplayName,
  isRoomLocator,
  isPeerId,
  isInviteToken,
  isInviteTokenHash,
  PROTOCOL_VERSION,
} from "../src/protocol.js";

test("PROTOCOL_VERSION is 1", () => {
  assert.equal(PROTOCOL_VERSION, 1);
});

test("parses a valid host.register frame", () => {
  const raw = JSON.stringify({
    v: 1,
    type: "host.register",
    inviteTokenHash: "a".repeat(64),
    inviteExpiresAt: Date.now() + 60000,
    recoverySecret: "test-recovery-secret-123456789", hostFingerprint: "host-fingerprint-1234",
    sessionName: "Friday night set",
  });
  const result = parseClientFrame(raw);
  assert.equal(result.ok, true);
  if (result.ok) {
    assert.equal(result.frame.type, "host.register");
  }
});

test("rejects a frame with the wrong protocol version", () => {
  const result = parseClientFrame(JSON.stringify({ v: 2, type: "ping" }));
  assert.equal(result.ok, false);
});

test("rejects malformed JSON", () => {
  const result = parseClientFrame("{not json");
  assert.equal(result.ok, false);
});

test("rejects unknown frame types", () => {
  const result = parseClientFrame(JSON.stringify({ v: 1, type: "totally.unknown" }));
  assert.equal(result.ok, false);
});

test("rejects guest.join with a bad roomLocator", () => {
  const result = parseClientFrame(
    JSON.stringify({
      v: 1,
      type: "guest.join",
      roomLocator: "not-hex",
      inviteToken: "a".repeat(22),
      displayName: "Guest",
      peerFingerprint: "fp",
    }),
  );
  assert.equal(result.ok, false);
});

test("sanitizeDisplayName trims and strips control characters", () => {
  const controlChar = String.fromCharCode(7);
  const withControls = "  Hello" + controlChar + "World  ";
  const cleaned = sanitizeDisplayName(withControls);
  assert.equal(cleaned, "HelloWorld");
});

test("sanitizeDisplayName rejects empty or too-long names", () => {
  assert.equal(sanitizeDisplayName("   "), null);
  assert.equal(sanitizeDisplayName("x".repeat(41)), null);
  assert.equal(sanitizeDisplayName("x".repeat(40)), "x".repeat(40));
});

test("guest.join sanitizes displayName through the full parse", () => {
  const result = parseClientFrame(
    JSON.stringify({
      v: 1,
      type: "guest.join",
      roomLocator: "a".repeat(32),
      inviteToken: "b".repeat(22),
      displayName: "  DJ Test  ",
      peerFingerprint: "fp-1",
    }),
  );
  assert.equal(result.ok, true);
  if (result.ok && result.frame.type === "guest.join") {
    assert.equal(result.frame.displayName, "DJ Test");
  }
});

test("validators accept only well-formed identifiers", () => {
  assert.equal(isRoomLocator("a".repeat(32)), true);
  assert.equal(isRoomLocator("A".repeat(32)), false);
  assert.equal(isRoomLocator("a".repeat(31)), false);
  assert.equal(isPeerId("f".repeat(24)), true);
  assert.equal(isPeerId("f".repeat(23)), false);
  assert.equal(isInviteToken("a".repeat(22)), true);
  assert.equal(isInviteToken("a".repeat(21)), false);
  assert.equal(isInviteTokenHash("a".repeat(64)), true);
  assert.equal(isInviteTokenHash("a".repeat(63)), false);
});

test("signal.relay carries an opaque payload untouched", () => {
  const payload = { sdp: "v=0", nested: { a: [1, 2, 3] } };
  const result = parseClientFrame(
    JSON.stringify({
      v: 1,
      type: "signal.relay",
      toPeerId: "a".repeat(24),
      payload,
    }),
  );
  assert.equal(result.ok, true);
  if (result.ok && result.frame.type === "signal.relay") {
    assert.deepEqual(result.frame.payload, payload);
  }
});
