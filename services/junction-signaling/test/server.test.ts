import { test } from "node:test";
import assert from "node:assert/strict";
import { WebSocket } from "ws";
import { randomBytes } from "node:crypto";
import { createJunctionServer, listen, type JunctionServer } from "../src/server.js";
import type { Config } from "../src/config.js";
import { createLogger } from "../src/logger.js";
import { hashInviteToken } from "../src/rooms.js";

function baseConfig(overrides: Partial<Config> = {}): Config {
  return {
    port: 0,
    host: "127.0.0.1",
    roomTtlSeconds: 3600,
    maxPeersPerRoom: 8,
    maxFrameBytes: 65536,
    relayRatePerSecond: 50,
    frameRatePerSecond: 200,
    joinAttemptsPerMinute: 10,
    allowedOrigins: null,
    trustProxy: false,
    logLevel: "error",
    ...overrides,
  };
}

interface StartedServer {
  server: JunctionServer;
  port: number;
  logLines: string[];
}

async function startServer(overrides: Partial<Config> = {}): Promise<StartedServer> {
  const logLines: string[] = [];
  const logger = createLogger({ level: "debug", write: (line) => logLines.push(line) });
  const server = createJunctionServer(baseConfig(overrides), logger);
  await listen(server, 0, "127.0.0.1");
  const { port } = server.address();
  return { server, port, logLines };
}

class TestClient {
  ws: WebSocket;
  private queue: any[] = [];
  private waiters: Array<(v: any) => void> = [];
  closedCode: number | null = null;

  constructor(port: number) {
    this.ws = new WebSocket(`ws://127.0.0.1:${port}`);
    this.ws.on("message", (data) => {
      const frame = JSON.parse(data.toString());
      const waiter = this.waiters.shift();
      if (waiter) waiter(frame);
      else this.queue.push(frame);
    });
    this.ws.on("close", (code) => {
      this.closedCode = code;
    });
  }

  waitOpen(): Promise<void> {
    return new Promise((resolve, reject) => {
      this.ws.once("open", () => resolve());
      this.ws.once("error", reject);
    });
  }

  waitClose(timeoutMs = 2000): Promise<number> {
    return new Promise((resolve, reject) => {
      if (this.closedCode !== null) {
        resolve(this.closedCode);
        return;
      }
      const timer = setTimeout(() => reject(new Error("timed out waiting for close")), timeoutMs);
      this.ws.once("close", (code) => {
        clearTimeout(timer);
        resolve(code);
      });
    });
  }

  next(timeoutMs = 2000): Promise<any> {
    if (this.queue.length > 0) {
      return Promise.resolve(this.queue.shift());
    }
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => reject(new Error("timed out waiting for frame")), timeoutMs);
      this.waiters.push((frame) => {
        clearTimeout(timer);
        resolve(frame);
      });
    });
  }

  send(frame: unknown): void {
    this.ws.send(JSON.stringify(frame));
  }

  sendRaw(raw: string): void {
    this.ws.send(raw);
  }

  close(): void {
    if (this.ws.readyState === WebSocket.OPEN || this.ws.readyState === WebSocket.CONNECTING) {
      this.ws.terminate();
    }
  }
}

async function connectClient(port: number): Promise<TestClient> {
  const client = new TestClient(port);
  await client.waitOpen();
  await client.next(); // server.hello
  return client;
}

function rawToken(): string {
  return randomBytes(20).toString("base64url");
}

test("host register -> guest join -> host accepts -> bidirectional relay of opaque payloads", async () => {
  const { server, port } = await startServer();
  try {
    const host = await connectClient(port);
    const inviteToken = rawToken();
    host.send({
      v: 1,
      type: "host.register",
      inviteTokenHash: hashInviteToken(inviteToken),
      inviteExpiresAt: Date.now() + 60_000,
      recoverySecret: "test-recovery-secret-123456789", hostFingerprint: "host-fingerprint-e2e-1",
      sessionName: "E2E Session",
    });
    const registered = await host.next();
    assert.equal(registered.type, "host.registered");
    const { roomLocator, hostPeerId } = registered;

    const guest = await connectClient(port);
    guest.send({
      v: 1,
      type: "guest.join",
      roomLocator,
      inviteToken,
      displayName: "Guest E2E",
      peerFingerprint: "guest-fp-e2e-1",
    });
    const pending = await guest.next();
    assert.equal(pending.type, "join.pending");
    const guestPeerId = pending.peerId;

    const joinRequest = await host.next();
    assert.equal(joinRequest.type, "room.join_request");
    assert.equal(joinRequest.guestPeerId, guestPeerId);

    host.send({ v: 1, type: "host.join_decision", guestPeerId, accept: true });
    const accepted = await guest.next();
    assert.equal(accepted.type, "join.accepted");
    assert.equal(accepted.hostPeerId, hostPeerId);

    const roster = await host.next();
    assert.equal(roster.type, "room.roster");
    assert.equal(roster.peers.length, 2);

    const opaquePayload = { sdp: "opaque-sdp-blob", candidates: [1, 2, 3] };
    host.send({ v: 1, type: "signal.relay", toPeerId: guestPeerId, payload: opaquePayload });
    await guest.next(); // admission roster
    const delivered = await guest.next();
    assert.equal(delivered.type, "signal.deliver");
    assert.deepEqual(delivered.payload, opaquePayload);
    assert.equal(delivered.fromPeerId, hostPeerId);

    const replyPayload = { ice: "opaque-ice-candidate" };
    guest.send({ v: 1, type: "signal.relay", toPeerId: hostPeerId, payload: replyPayload });
    const deliveredBack = await host.next();
    assert.equal(deliveredBack.type, "signal.deliver");
    assert.deepEqual(deliveredBack.payload, replyPayload);

    host.close();
    guest.close();
  } finally {
    await server.close();
  }
});

test("wrong token and unknown room both yield invalid_invite (no room-existence leak)", async () => {
  const { server, port } = await startServer();
  try {
    const host = await connectClient(port);
    const inviteToken = rawToken();
    host.send({
      v: 1,
      type: "host.register",
      inviteTokenHash: hashInviteToken(inviteToken),
      inviteExpiresAt: Date.now() + 60_000,
      recoverySecret: "test-recovery-secret-123456789", hostFingerprint: "host-fp-wrongtoken",
      sessionName: "Session",
    });
    const registered = await host.next();

    const guestBadToken = await connectClient(port);
    guestBadToken.send({
      v: 1,
      type: "guest.join",
      roomLocator: registered.roomLocator,
      inviteToken: rawToken(),
      displayName: "Bad Token",
      peerFingerprint: "fp-bad",
    });
    const rejectedBadToken = await guestBadToken.next();
    assert.equal(rejectedBadToken.type, "join.rejected");
    assert.equal(rejectedBadToken.reason, "invalid_invite");

    const guestUnknownRoom = await connectClient(port);
    guestUnknownRoom.send({
      v: 1,
      type: "guest.join",
      roomLocator: "f".repeat(32),
      inviteToken: rawToken(),
      displayName: "Unknown Room",
      peerFingerprint: "fp-unknown",
    });
    const rejectedUnknownRoom = await guestUnknownRoom.next();
    assert.equal(rejectedUnknownRoom.type, "join.rejected");
    assert.equal(rejectedUnknownRoom.reason, "invalid_invite");

    host.close();
    guestBadToken.close();
    guestUnknownRoom.close();
  } finally {
    await server.close();
  }
});

test("expired invite and revoked invite are rejected with distinct reasons", async () => {
  const { server, port } = await startServer();
  try {
    const host = await connectClient(port);
    const inviteToken = rawToken();
    host.send({
      v: 1,
      type: "host.register",
      inviteTokenHash: hashInviteToken(inviteToken),
      inviteExpiresAt: Date.now() + 300,
      recoverySecret: "test-recovery-secret-123456789", hostFingerprint: "host-fp-expiryxx",
      sessionName: "Session",
    });
    const registered = await host.next();

    await new Promise((r) => setTimeout(r, 500));

    const guestExpired = await connectClient(port);
    guestExpired.send({
      v: 1,
      type: "guest.join",
      roomLocator: registered.roomLocator,
      inviteToken,
      displayName: "Expired",
      peerFingerprint: "fp-expired",
    });
    const rejectedExpired = await guestExpired.next();
    assert.equal(rejectedExpired.reason, "expired_invite");

    const newToken = rawToken();
    host.send({
      v: 1,
      type: "host.rotate_invite",
      inviteTokenHash: hashInviteToken(newToken),
      inviteExpiresAt: Date.now() + 60_000,
    });
    await host.next(); // host.invite_rotated

    host.send({ v: 1, type: "host.revoke_invite" });
    await host.next(); // host.invite_revoked

    const guestRevoked = await connectClient(port);
    guestRevoked.send({
      v: 1,
      type: "guest.join",
      roomLocator: registered.roomLocator,
      inviteToken: newToken,
      displayName: "Revoked",
      peerFingerprint: "fp-revoked",
    });
    const rejectedRevoked = await guestRevoked.next();
    assert.equal(rejectedRevoked.reason, "revoked_invite");

    host.close();
    guestExpired.close();
    guestRevoked.close();
  } finally {
    await server.close();
  }
});

test("11 bad join attempts against the same room trip too_many_attempts", async () => {
  const { server, port } = await startServer({ joinAttemptsPerMinute: 10 });
  try {
    const host = await connectClient(port);
    const inviteToken = rawToken();
    host.send({
      v: 1,
      type: "host.register",
      inviteTokenHash: hashInviteToken(inviteToken),
      inviteExpiresAt: Date.now() + 60_000,
      recoverySecret: "test-recovery-secret-123456789", hostFingerprint: "host-fp-bruteforce",
      sessionName: "Session",
    });
    const registered = await host.next();

    const reasons: string[] = [];
    for (let i = 0; i < 11; i++) {
      const guest = await connectClient(port);
      guest.send({
        v: 1,
        type: "guest.join",
        roomLocator: registered.roomLocator,
        inviteToken: rawToken(),
        displayName: `Attempt ${i}`,
        peerFingerprint: `fp-attempt-${i}`,
      });
      const rejected = await guest.next();
      reasons.push(rejected.reason);
      guest.close();
    }

    assert.equal(reasons[10], "too_many_attempts");
    assert.ok(reasons.slice(0, 10).every((r) => r === "invalid_invite"));

    host.close();
  } finally {
    await server.close();
  }
});

test("maxPeers is enforced with room_full", async () => {
  const { server, port } = await startServer();
  try {
    const host = await connectClient(port);
    const inviteToken = rawToken();
    host.send({
      v: 1,
      type: "host.register",
      inviteTokenHash: hashInviteToken(inviteToken),
      inviteExpiresAt: Date.now() + 60_000,
      recoverySecret: "test-recovery-secret-123456789", hostFingerprint: "host-fp-maxpeers",
      sessionName: "Session",
      maxPeers: 2,
    });
    const registered = await host.next();

    const guestA = await connectClient(port);
    guestA.send({
      v: 1,
      type: "guest.join",
      roomLocator: registered.roomLocator,
      inviteToken,
      displayName: "Guest A",
      peerFingerprint: "fp-a",
    });
    const pendingA = await guestA.next();
    assert.equal(pendingA.type, "join.pending");
    await host.next(); // room.join_request for A

    const guestB = await connectClient(port);
    guestB.send({
      v: 1,
      type: "guest.join",
      roomLocator: registered.roomLocator,
      inviteToken,
      displayName: "Guest B",
      peerFingerprint: "fp-b",
    });
    const rejectedB = await guestB.next();
    assert.equal(rejectedB.type, "join.rejected");
    assert.equal(rejectedB.reason, "room_full");

    host.close();
    guestA.close();
    guestB.close();
  } finally {
    await server.close();
  }
});

test("relay to a non-member peerId is refused, and cross-room relay is impossible", async () => {
  const { server, port } = await startServer();
  try {
    const hostA = await connectClient(port);
    const tokenA = rawToken();
    hostA.send({
      v: 1,
      type: "host.register",
      inviteTokenHash: hashInviteToken(tokenA),
      inviteExpiresAt: Date.now() + 60_000,
      recoverySecret: "test-recovery-secret-123456789", hostFingerprint: "host-fp-room-axx",
      sessionName: "Room A",
    });
    const registeredA = await hostA.next();

    const hostB = await connectClient(port);
    const tokenB = rawToken();
    hostB.send({
      v: 1,
      type: "host.register",
      inviteTokenHash: hashInviteToken(tokenB),
      inviteExpiresAt: Date.now() + 60_000,
      recoverySecret: "test-recovery-secret-123456789", hostFingerprint: "host-fp-room-bxx",
      sessionName: "Room B",
    });
    const registeredB = await hostB.next();

    // Non-member random peerId.
    hostA.send({
      v: 1,
      type: "signal.relay",
      toPeerId: "a".repeat(24),
      payload: { hello: "world" },
    });
    const err1 = await hostA.next();
    assert.equal(err1.type, "error");
    assert.equal(err1.code, "peer_unreachable");

    // Cross-room: host A tries to relay to host B's real peerId.
    hostA.send({
      v: 1,
      type: "signal.relay",
      toPeerId: registeredB.hostPeerId,
      payload: { hello: "world" },
    });
    const err2 = await hostA.next();
    assert.equal(err2.type, "error");
    assert.equal(err2.code, "peer_unreachable");

    hostA.close();
    hostB.close();
  } finally {
    await server.close();
  }
});

test("frames over maxFrameBytes are rejected by the parser with close 1009", async () => {
  const { server, port } = await startServer({ maxFrameBytes: 1024 });
  try {
    const client = await connectClient(port);
    const hugePayload = "x".repeat(2000);
    client.sendRaw(JSON.stringify({ v: 1, type: "ping", filler: hugePayload }));
    const code = await client.waitClose();
    assert.equal(code, 1009);
  } finally {
    await server.close();
  }
});

test("room TTL expiry reports signaling unavailability", async () => {
  const { server, port } = await startServer({ roomTtlSeconds: 1 });
  try {
    const host = await connectClient(port);
    const inviteToken = rawToken();
    host.send({
      v: 1,
      type: "host.register",
      inviteTokenHash: hashInviteToken(inviteToken),
      inviteExpiresAt: Date.now() + 900,
      recoverySecret: "test-recovery-secret-123456789", hostFingerprint: "host-fp-ttlxxxxx",
      sessionName: "Session",
    });
    await host.next(); // host.registered

    const closed = await host.next(10_000);
    assert.equal(closed.type, "signaling.unavailable");
    assert.equal(closed.reason, "expired");

    host.close();
  } finally {
    await server.close();
  }
});

test("host disconnect reports signaling unavailability without ending session", async () => {
  const { server, port } = await startServer();
  try {
    const host = await connectClient(port);
    const inviteToken = rawToken();
    host.send({
      v: 1,
      type: "host.register",
      inviteTokenHash: hashInviteToken(inviteToken),
      inviteExpiresAt: Date.now() + 60_000,
      recoverySecret: "test-recovery-secret-123456789", hostFingerprint: "host-fp-disconnect",
      sessionName: "Session",
    });
    const registered = await host.next();

    const guest = await connectClient(port);
    guest.send({
      v: 1,
      type: "guest.join",
      roomLocator: registered.roomLocator,
      inviteToken,
      displayName: "Guest",
      peerFingerprint: "fp-disc",
    });
    const pending = await guest.next();
    await host.next(); // room.join_request
    host.send({ v: 1, type: "host.join_decision", guestPeerId: pending.peerId, accept: true });
    await guest.next(); // join.accepted
    await guest.next(); // roster

    host.close();

    const closedForGuest = await guest.next(5000);
    assert.equal(closedForGuest.type, "signaling.unavailable");
    assert.equal(closedForGuest.reason, "host_disconnected");

    guest.close();
  } finally {
    await server.close();
  }
});

test("log output never contains the raw invite token", async () => {
  const { server, port, logLines } = await startServer();
  try {
    const host = await connectClient(port);
    const inviteToken = rawToken();
    host.send({
      v: 1,
      type: "host.register",
      inviteTokenHash: hashInviteToken(inviteToken),
      inviteExpiresAt: Date.now() + 60_000,
      recoverySecret: "test-recovery-secret-123456789", hostFingerprint: "host-fp-logredact",
      sessionName: "Session",
    });
    const registered = await host.next();

    const guest = await connectClient(port);
    guest.send({
      v: 1,
      type: "guest.join",
      roomLocator: registered.roomLocator,
      inviteToken,
      displayName: "Guest",
      peerFingerprint: "fp-logredact",
    });
    await guest.next(); // join.pending
    await host.next(); // room.join_request

    // Also try a wrong token so a "failed" attempt path logs too.
    const guestBad = await connectClient(port);
    const wrongToken = rawToken();
    guestBad.send({
      v: 1,
      type: "guest.join",
      roomLocator: registered.roomLocator,
      inviteToken: wrongToken,
      displayName: "Bad",
      peerFingerprint: "fp-bad-log",
    });
    await guestBad.next();

    const combined = logLines.join("\n");
    assert.ok(!combined.includes(inviteToken), "raw invite token leaked into logs");
    assert.ok(!combined.includes(wrongToken), "raw wrong token leaked into logs");

    host.close();
    guest.close();
    guestBad.close();
  } finally {
    await server.close();
  }
});

test("graceful shutdown reports signaling unavailability", async () => {
  const { server, port } = await startServer();
  const host = await connectClient(port);
  const inviteToken = rawToken();
  host.send({
    v: 1,
    type: "host.register",
    inviteTokenHash: hashInviteToken(inviteToken),
    inviteExpiresAt: Date.now() + 60_000,
    recoverySecret: "test-recovery-secret-123456789", hostFingerprint: "host-fp-shutdown",
    sessionName: "Session",
  });
  await host.next(); // host.registered

  await server.shutdown();

  const closed = await host.next(2000);
  assert.equal(closed.type, "signaling.unavailable");
  assert.equal(closed.reason, "server_shutdown");

  host.close();
});

test("host public fingerprint cannot reclaim without recovery secret; valid recovery removes stale privileges", async () => {
  const { server, port } = await startServer();
  try {
    const a = await connectClient(port);
    const registration = { v: 1, type: "host.register", recoverySecret: rawToken(), hostFingerprint: "host-fingerprint-recovery", sessionName: "Recovery", inviteTokenHash: hashInviteToken(rawToken()), inviteExpiresAt: Date.now() + 60000 };
    a.send(registration);
    const original = await a.next();
    const b = await connectClient(port);
    b.send({ ...registration, roomLocator: original.roomLocator, recoverySecret: rawToken() });
    assert.equal((await b.next()).code, "room_claimed");
    b.send({ ...registration, roomLocator: original.roomLocator });
    assert.equal((await b.next()).hostPeerId, original.hostPeerId);
    a.send({ v: 1, type: "host.heartbeat" });
    assert.equal((await a.next()).code, "not_authorized");
    a.close();
    b.send({ v: 1, type: "host.heartbeat" });
    assert.equal((await b.next()).type, "host.heartbeat.ack");
  } finally { await server.close(); }
});

test("TURN credentials require admitted membership and expire with coturn HMAC", async () => {
  const secret = "private-coturn-secret-01234567890123456789";
  const { server, port, logLines } = await startServer({ turnUrls: ["turn:relay.example.invalid:3478"], turnSecret: secret, turnTtlSeconds: 300 });
  try {
    const client = await connectClient(port);
    client.send({ v: 1, type: "turn.credentials" });
    assert.equal((await client.next()).code, "not_authorized");
    client.send({ v: 1, type: "host.register", recoverySecret: rawToken(), hostFingerprint: "host-fingerprint-turn", sessionName: "TURN", inviteTokenHash: hashInviteToken(rawToken()), inviteExpiresAt: Date.now() + 60000 });
    const registered = await client.next();
    client.send({ v: 1, type: "turn.credentials" });
    const frame = await client.next();
    const { createHmac } = await import("node:crypto");
    assert.equal(frame.iceServers[0].credential, createHmac("sha1", secret).update(frame.iceServers[0].username).digest("base64"));
    assert.ok(frame.iceServers[0].username.endsWith(`:${registered.hostPeerId}`));
    assert.ok(frame.expiresAt > Date.now() && frame.expiresAt <= Date.now() + 300000);
    assert.ok(!logLines.join("").includes(frame.iceServers[0].credential));
  } finally { await server.close(); }
});
