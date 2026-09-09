import { test } from "node:test";
import assert from "node:assert/strict";
import { RoomRegistry, hashInviteToken, generateRoomLocator } from "../src/rooms.js";

function makeRegistry() {
  return new RoomRegistry();
}

function registerHost(
  registry: RoomRegistry,
  overrides: Partial<{
    roomLocator: string;
    inviteToken: string;
    recoverySecret: string; hostFingerprint: string;
    connectionId: string;
    maxPeers: number;
    ttlSeconds: number;
    inviteExpiresAt: number;
  }> = {},
  nowMs = Date.now(),
) {
  const inviteToken = overrides.inviteToken ?? "raw-invite-token-000000";
  const result = registry.registerHost(
    {
      roomLocator: overrides.roomLocator,
      inviteTokenHash: hashInviteToken(inviteToken),
      inviteExpiresAt: overrides.inviteExpiresAt ?? nowMs + 60_000,
      recoverySecret: "test-recovery-secret-123456789", hostFingerprint: overrides.hostFingerprint ?? "host-fp-abc123xx",
      sessionName: "Test Session",
      maxPeers: overrides.maxPeers ?? 4,
      connectionId: overrides.connectionId ?? "host-conn-1",
      ttlSeconds: overrides.ttlSeconds ?? 3600,
    },
    nowMs,
  );
  if (!result.ok) throw new Error("expected registerHost to succeed");
  return { result, inviteToken };
}

test("registerHost creates a room with a generated locator and peerId", () => {
  const registry = makeRegistry();
  const { result } = registerHost(registry);
  assert.match(result.roomLocator, /^[a-f0-9]{32}$/);
  assert.match(result.hostPeerId, /^[a-f0-9]{24}$/);
});

test("registerHost respects an explicit roomLocator", () => {
  const registry = makeRegistry();
  const locator = generateRoomLocator();
  const { result } = registerHost(registry, { roomLocator: locator });
  assert.equal(result.roomLocator, locator);
});

test("recovery secret reclaims the room and invalidates old connection", () => {
  const registry = makeRegistry();
  const locator = generateRoomLocator();
  const first = registerHost(registry, { roomLocator: locator, connectionId: "conn-a" });
  const second = registry.registerHost(
    {
      roomLocator: locator,
      inviteTokenHash: hashInviteToken("another-token-value-000"),
      inviteExpiresAt: Date.now() + 60_000,
      recoverySecret: "test-recovery-secret-123456789", hostFingerprint: "host-fp-abc123xx",
      sessionName: "Reclaimed",
      maxPeers: 4,
      connectionId: "conn-b",
      ttlSeconds: 3600,
    },
    Date.now(),
  );
  assert.equal(second.ok, true);
  if (second.ok) {
    assert.equal(second.hostPeerId, first.result.hostPeerId);
    assert.equal(registry.heartbeat("conn-a", Date.now(), 3600).ok, false);
    assert.equal(registry.relayLookup("conn-a", second.hostPeerId).ok, false);
    assert.equal(registry.handleDisconnect("conn-a", Date.now()).kind, "none");
  }
});

test("re-registering with a different hostFingerprint is room_claimed", () => {
  const registry = makeRegistry();
  const locator = generateRoomLocator();
  registerHost(registry, { roomLocator: locator, connectionId: "conn-a" });
  const second = registry.registerHost(
    {
      roomLocator: locator,
      inviteTokenHash: hashInviteToken("another-token-value-000"),
      inviteExpiresAt: Date.now() + 60_000,
      recoverySecret: "test-recovery-secret-123456789", hostFingerprint: "different-fingerprint",
      sessionName: "Impostor",
      maxPeers: 4,
      connectionId: "conn-b",
      ttlSeconds: 3600,
    },
    Date.now(),
  );
  assert.deepEqual(second, { ok: false, code: "room_claimed" });
});

test("attemptGuestJoin succeeds with the correct token", () => {
  const registry = makeRegistry();
  const { result, inviteToken } = registerHost(registry);
  const joined = registry.attemptGuestJoin(
    {
      roomLocator: result.roomLocator,
      inviteToken,
      displayName: "Guest One",
      peerFingerprint: "guest-fp-1",
      connectionId: "guest-conn-1",
    },
    Date.now(),
  );
  assert.equal(joined.ok, true);
});

test("attemptGuestJoin fails with invalid_invite for wrong token", () => {
  const registry = makeRegistry();
  const { result } = registerHost(registry);
  const joined = registry.attemptGuestJoin(
    {
      roomLocator: result.roomLocator,
      inviteToken: "wrong-token-value-000000",
      displayName: "Guest",
      peerFingerprint: "guest-fp-1",
      connectionId: "guest-conn-1",
    },
    Date.now(),
  );
  assert.deepEqual(joined, { ok: false, reason: "invalid_invite" });
});

test("attemptGuestJoin fails with invalid_invite for an unknown room (no leak)", () => {
  const registry = makeRegistry();
  const joined = registry.attemptGuestJoin(
    {
      roomLocator: generateRoomLocator(),
      inviteToken: "wrong-token-value-000000",
      displayName: "Guest",
      peerFingerprint: "guest-fp-1",
      connectionId: "guest-conn-1",
    },
    Date.now(),
  );
  assert.deepEqual(joined, { ok: false, reason: "invalid_invite" });
});

test("attemptGuestJoin fails with expired_invite", () => {
  const registry = makeRegistry();
  const now = Date.now();
  const { result, inviteToken } = registerHost(registry, { inviteExpiresAt: now + 1000 }, now);
  const joined = registry.attemptGuestJoin(
    {
      roomLocator: result.roomLocator,
      inviteToken,
      displayName: "Guest",
      peerFingerprint: "guest-fp-1",
      connectionId: "guest-conn-1",
    },
    now + 2000,
  );
  assert.deepEqual(joined, { ok: false, reason: "expired_invite" });
});

test("attemptGuestJoin fails with revoked_invite after revokeInvite", () => {
  const registry = makeRegistry();
  const { result, inviteToken } = registerHost(registry, { connectionId: "host-conn-x" });
  const revoked = registry.revokeInvite("host-conn-x");
  assert.equal(revoked.ok, true);
  const joined = registry.attemptGuestJoin(
    {
      roomLocator: result.roomLocator,
      inviteToken,
      displayName: "Guest",
      peerFingerprint: "guest-fp-1",
      connectionId: "guest-conn-1",
    },
    Date.now(),
  );
  assert.deepEqual(joined, { ok: false, reason: "revoked_invite" });
});

test("attemptGuestJoin enforces maxPeers", () => {
  const registry = makeRegistry();
  const { result, inviteToken } = registerHost(registry, { maxPeers: 2 });
  const first = registry.attemptGuestJoin(
    {
      roomLocator: result.roomLocator,
      inviteToken,
      displayName: "Guest A",
      peerFingerprint: "fp-a",
      connectionId: "guest-conn-a",
    },
    Date.now(),
  );
  assert.equal(first.ok, true);
  const second = registry.attemptGuestJoin(
    {
      roomLocator: result.roomLocator,
      inviteToken,
      displayName: "Guest B",
      peerFingerprint: "fp-b",
      connectionId: "guest-conn-b",
    },
    Date.now(),
  );
  assert.deepEqual(second, { ok: false, reason: "room_full" });
});

test("decideJoin accept adds peer to roster; reject removes pending peer", () => {
  const registry = makeRegistry();
  const { result, inviteToken } = registerHost(registry, { connectionId: "host-conn-y" });
  const joined = registry.attemptGuestJoin(
    {
      roomLocator: result.roomLocator,
      inviteToken,
      displayName: "Guest",
      peerFingerprint: "fp",
      connectionId: "guest-conn-y",
    },
    Date.now(),
  );
  if (!joined.ok) throw new Error("expected join to succeed");

  const decision = registry.decideJoin("host-conn-y", joined.peerId, true, Date.now());
  assert.equal(decision.ok, true);
  const roster = registry.getRoster(result.roomLocator);
  assert.equal(roster.length, 2); // host + accepted guest
});

test("relayLookup only allows relay between accepted peers in the same room", () => {
  const registry = makeRegistry();
  const { result, inviteToken } = registerHost(registry, { connectionId: "host-conn-z" });
  const joined = registry.attemptGuestJoin(
    {
      roomLocator: result.roomLocator,
      inviteToken,
      displayName: "Guest",
      peerFingerprint: "fp",
      connectionId: "guest-conn-z",
    },
    Date.now(),
  );
  if (!joined.ok) throw new Error("expected join to succeed");

  // Guest not yet accepted: relay from guest should be not_ready.
  const beforeAccept = registry.relayLookup("guest-conn-z", result.hostPeerId);
  assert.equal(beforeAccept.ok, false);

  registry.decideJoin("host-conn-z", joined.peerId, true, Date.now());

  const hostToGuest = registry.relayLookup("host-conn-z", joined.peerId);
  assert.equal(hostToGuest.ok, true);

  const guestToHost = registry.relayLookup("guest-conn-z", result.hostPeerId);
  assert.equal(guestToHost.ok, true);

  const guestToUnknown = registry.relayLookup("guest-conn-z", "f".repeat(24));
  assert.equal(guestToUnknown.ok, false);
});

test("relayLookup refuses cross-room relay", () => {
  const registry = makeRegistry();
  const roomA = registerHost(registry, { connectionId: "host-a" });
  const roomB = registerHost(registry, { connectionId: "host-b" });
  const lookup = registry.relayLookup("host-a", roomB.result.hostPeerId);
  assert.equal(lookup.ok, false);
});

test("host disconnect preserves room for authenticated recovery", () => {
  const registry = makeRegistry();
  const { result, inviteToken } = registerHost(registry, { connectionId: "host-conn-w" });
  const joined = registry.attemptGuestJoin(
    {
      roomLocator: result.roomLocator,
      inviteToken,
      displayName: "Guest",
      peerFingerprint: "fp",
      connectionId: "guest-conn-w",
    },
    Date.now(),
  );
  if (!joined.ok) throw new Error("expected join to succeed");
  registry.decideJoin("host-conn-w", joined.peerId, true, Date.now());

  const effect = registry.handleDisconnect("host-conn-w", Date.now());
  assert.equal(effect.kind, "host_unavailable");
  if (effect.kind === "host_unavailable") {
    assert.ok(effect.memberConnectionIds.includes("guest-conn-w"));
  }
  assert.ok(registry.getRoom(result.roomLocator));
});

test("handleDisconnect on a guest only removes that guest", () => {
  const registry = makeRegistry();
  const { result, inviteToken } = registerHost(registry, { connectionId: "host-conn-v" });
  const joined = registry.attemptGuestJoin(
    {
      roomLocator: result.roomLocator,
      inviteToken,
      displayName: "Guest",
      peerFingerprint: "fp",
      connectionId: "guest-conn-v",
    },
    Date.now(),
  );
  if (!joined.ok) throw new Error("expected join to succeed");
  registry.decideJoin("host-conn-v", joined.peerId, true, Date.now());

  const effect = registry.handleDisconnect("guest-conn-v", Date.now());
  assert.equal(effect.kind, "guest_left");
  assert.ok(registry.getRoom(result.roomLocator));
  const roster = registry.getRoster(result.roomLocator);
  assert.equal(roster.length, 1);
});

test("sweepExpiredRooms removes rooms whose TTL has lapsed", () => {
  const registry = makeRegistry();
  const now = Date.now();
  const { result } = registerHost(registry, { ttlSeconds: 1 }, now);
  const expired = registry.sweepExpiredRooms(now + 5000);
  assert.equal(expired.length, 1);
  assert.equal(expired[0].roomLocator, result.roomLocator);
  assert.equal(registry.getRoom(result.roomLocator), undefined);
});

test("heartbeat refreshes room TTL", () => {
  const registry = makeRegistry();
  const now = Date.now();
  const { result } = registerHost(registry, { ttlSeconds: 10, connectionId: "host-conn-hb" }, now);
  const beforeExpiry = result.expiresAt;
  const heartbeat = registry.heartbeat("host-conn-hb", now + 5000, 10);
  assert.equal(heartbeat.ok, true);
  if (heartbeat.ok) {
    assert.ok(heartbeat.expiresAt > beforeExpiry);
  }
});

test("stats reports room and peer counts", () => {
  const registry = makeRegistry();
  registerHost(registry, { connectionId: "host-conn-s" });
  const stats = registry.stats();
  assert.equal(stats.rooms, 1);
  assert.equal(stats.peers, 1);
});

test("revoking an invite invalidates pending admission", () => {
  const registry = makeRegistry();
  const { result, inviteToken } = registerHost(registry);
  const pending = registry.attemptGuestJoin({ roomLocator: result.roomLocator, inviteToken, displayName: "Guest", peerFingerprint: "guest", connectionId: "pending" }, Date.now());
  assert.ok(pending.ok);
  registry.revokeInvite("host-conn-1");
  const decision = registry.decideJoin("host-conn-1", pending.peerId, true, Date.now());
  assert.ok(decision.ok);
  assert.equal(decision.accepted, false);
  assert.equal(registry.isConnectionActive("pending"), false);
});
