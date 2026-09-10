// ws wiring, HTTP health endpoints, and graceful shutdown for the
// plumdeck Junction signaling service. This is the only module allowed to
// import `ws`/`http` — protocol.ts, rooms.ts and rate-limit.ts stay pure.

import { createServer, type Server as HttpServer } from "node:http";
import { randomUUID, createHmac } from "node:crypto";
import { WebSocketServer, WebSocket, type RawData } from "ws";
import type { Config } from "./config.js";
import type { Logger } from "./logger.js";
import { truncateRoomLocator } from "./logger.js";
import {
  PROTOCOL_VERSION,
  parseClientFrame,
  isPeerId,
  type ServerFrame,
  type ClientFrame,
  type ErrorCode,
  type JoinRejectReason,
} from "./protocol.js";
import { RoomRegistry, hashInviteToken } from "./rooms.js";
import { TokenBucket, AttemptCounter, StrikeCounter } from "./rate-limit.js";

// Re-exported so index.ts / tests never import the "ws" package directly
// just to get a version string.
const PACKAGE_VERSION = "0.1.0";

interface ConnectionCtx {
  maxBufferedBytes: number;
  connectionId: string;
  socket: WebSocket;
  ip: string;
  isAlive: boolean;
  missedPongs: number;
  frameBucket: TokenBucket;
  relayBucket: TokenBucket;
  strikes: StrikeCounter;
  hasHostedOrJoined: boolean;
}

export interface JunctionServer {
  httpServer: HttpServer;
  wss: WebSocketServer;
  close(): Promise<void>;
  /** Announces signaling unavailability, preserving native P2P sessions. */
  shutdown(): Promise<void>;
  address(): { port: number; host: string };
}

function send(ctx: ConnectionCtx, frame: ServerFrame): void {
  if (ctx.socket.readyState !== WebSocket.OPEN) return;
  const text = JSON.stringify(frame);
  if (ctx.socket.bufferedAmount + Buffer.byteLength(text) > ctx.maxBufferedBytes) { ctx.socket.terminate(); return; }
  ctx.socket.send(text);
}

function sendError(
  ctx: ConnectionCtx,
  code: ErrorCode,
  message: string,
): void {
  send(ctx, { v: 1, type: "error", code, message });
}

function clientIp(req: { socket: { remoteAddress?: string }; headers: Record<string, string | string[] | undefined> }, trustProxy: boolean): string {
  if (trustProxy) {
    const xff = req.headers["x-forwarded-for"];
    const first = Array.isArray(xff) ? xff[0] : xff;
    if (first) {
      const ip = first.split(",")[0]?.trim();
      if (ip) return ip;
    }
  }
  return req.socket.remoteAddress ?? "unknown";
}

export function createJunctionServer(
  config: Config,
  logger: Logger,
): JunctionServer {
  const registry = new RoomRegistry();
  const roomAttemptCounter = new AttemptCounter(60_000, config.joinAttemptsPerMinute);
  const ipAttemptCounter = new AttemptCounter(60_000, config.joinAttemptsPerMinute * 4);
  const connections = new Map<string, ConnectionCtx>();

  const httpServer = createServer((req, res) => {
    if (req.url === "/healthz") {
      const stats = registry.stats();
      res.writeHead(200, { "content-type": "application/json" });
      res.end(
        JSON.stringify({
          status: "ok",
          rooms: stats.rooms,
          peers: stats.peers,
          uptimeSeconds: Math.floor(process.uptime()),
        }),
      );
      return;
    }
    if (req.url === "/readyz") {
      res.writeHead(200, { "content-type": "application/json" });
      res.end(JSON.stringify({ status: "ready" }));
      return;
    }
    res.writeHead(404, { "content-type": "application/json" });
    res.end(JSON.stringify({ error: "not_found" }));
  });

  const wss = new WebSocketServer({ noServer: true, maxPayload: config.maxFrameBytes, perMessageDeflate: false });

  httpServer.on("upgrade", (req, socket, head) => {
    if (connections.size >= (config.maxConnections ?? 1024) || shuttingDown || (req.url !== "/" && req.url !== "/ws")) { socket.destroy(); return; }
    if (config.allowedOrigins) {
      const origin = req.headers.origin;
      if (!origin || !config.allowedOrigins.includes(origin)) {
        socket.write("HTTP/1.1 403 Forbidden\r\n\r\n");
        socket.destroy();
        return;
      }
    }
    wss.handleUpgrade(req, socket, head, (ws) => {
      wss.emit("connection", ws, req);
    });
  });

  let shuttingDown = false;

  wss.on("connection", (ws: WebSocket, req) => {
    if (shuttingDown) {
      ws.close(1001, "server shutting down");
      return;
    }
    const connectionId = randomUUID();
    const ip = clientIp(req as any, config.trustProxy);
    const ctx: ConnectionCtx = {
      maxBufferedBytes: config.maxBufferedBytes ?? 262144,
      connectionId,
      socket: ws,
      ip,
      isAlive: true,
      missedPongs: 0,
      frameBucket: new TokenBucket(
        config.frameRatePerSecond * 2,
        config.frameRatePerSecond,
      ),
      relayBucket: new TokenBucket(
        Math.max(config.relayRatePerSecond * 2, 100),
        config.relayRatePerSecond,
      ),
      strikes: new StrikeCounter(3),
      hasHostedOrJoined: false,
    };
    connections.set(connectionId, ctx);

    logger.info("connection.open", { connectionId, ip });

    send(ctx, {
      v: 1,
      type: "server.hello",
      protocolVersion: PROTOCOL_VERSION,
      serverVersion: PACKAGE_VERSION,
      limits: {
        maxFrameBytes: config.maxFrameBytes,
        maxRoomTtlSeconds: config.roomTtlSeconds,
        maxPeersPerRoom: config.maxPeersPerRoom,
        relayRatePerSecond: config.relayRatePerSecond,
        joinAttemptsPerRoomPerMinute: config.joinAttemptsPerMinute,
      },
    });

    ws.on("pong", () => {
      ctx.isAlive = true;
      ctx.missedPongs = 0;
    });

    ws.on("message", (data: RawData, isBinary: boolean) => {
      handleMessage(ctx, data, isBinary);
    });

    ws.on("close", () => {
      connections.delete(connectionId);
      const effect = registry.handleDisconnect(connectionId, Date.now());
      applyDisconnectEffect(effect);
      logger.info("connection.close", { connectionId });
    });

    ws.on("error", (err: Error) => {
      logger.warn("connection.error", { connectionId, message: err.message });
    });
  });

  function applyDisconnectEffect(
    effect: ReturnType<RoomRegistry["handleDisconnect"]>,
  ): void {
    if (effect.kind === "none") return;
    if (effect.kind === "host_unavailable") {
      broadcastTo(effect.memberConnectionIds, { v: 1, type: "signaling.unavailable", reason: "host_disconnected" });
      return;
    }
    if (effect.kind === "guest_left") {
      broadcastTo(effect.remainingConnectionIds, {
        v: 1,
        type: "peer.gone",
        peerId: effect.removedPeerId,
        reason: "disconnected",
      });
      broadcastTo(effect.remainingConnectionIds, {
        v: 1,
        type: "room.roster",
        peers: effect.roster,
      });
      return;
    }
    if (effect.kind === "room_closed") {
      broadcastTo(effect.memberConnectionIds, {
        v: 1,
        type: "room.closed",
        reason: effect.reason,
      });
      for (const cid of effect.memberConnectionIds) {
        const member = connections.get(cid);
        member?.socket.close(1000, "room closed");
      }
    }
  }

  function broadcastTo(connectionIds: string[], frame: ServerFrame): void {
    for (const cid of connectionIds) {
      const ctx = connections.get(cid);
      if (ctx) send(ctx, frame);
    }
  }

  function strikeAndMaybeClose(ctx: ConnectionCtx): boolean {
    const tripped = ctx.strikes.strike();
    if (tripped) {
      logger.warn("connection.rate_limit_abuse", {
        connectionId: ctx.connectionId,
      });
      ctx.socket.close(1008, "rate limit abuse");
      return true;
    }
    return false;
  }

  function handleMessage(
    ctx: ConnectionCtx,
    data: RawData,
    isBinary: boolean,
  ): void {
    const buf = Buffer.isBuffer(data)
      ? data
      : Array.isArray(data)
        ? Buffer.concat(data)
        : Buffer.from(data as ArrayBuffer);

    if (buf.byteLength > config.maxFrameBytes) {
      sendError(ctx, "frame_too_large", "frame exceeds maxFrameBytes");
      ctx.socket.close(1009, "frame too large");
      return;
    }

    if (!ctx.frameBucket.take(1)) {
      sendError(ctx, "rate_limited", "frame rate exceeded");
      strikeAndMaybeClose(ctx);
      return;
    }

    if (isBinary) {
      sendError(ctx, "bad_frame", "binary frames are not supported");
      return;
    }

    const raw = buf.toString("utf8");
    const parsed = parseClientFrame(raw);
    if (!parsed.ok) {
      sendError(ctx, "bad_frame", parsed.error);
      return;
    }
    dispatch(ctx, parsed.frame);
  }

  function dispatch(ctx: ConnectionCtx, frame: ClientFrame): void {
    const now = Date.now();
    // Enforce TTL at dispatch as well as during the periodic sweep.
    for (const expired of registry.sweepExpiredRooms(now)) {
      broadcastTo(expired.memberConnectionIds, { v: 1, type: "signaling.unavailable", reason: "expired" });
    }
    switch (frame.type) {
      case "host.register": {
        if (ipAttemptCounter.isBlocked(ctx.ip, now)) { sendError(ctx, "rate_limited", "registration budget exceeded"); return; }
        ipAttemptCounter.recordFailure(ctx.ip, now);
        if (registry.isConnectionActive(ctx.connectionId)) {
          sendError(ctx, "already_registered", "connection already hosts or joined a room");
          return;
        }
        if ((!frame.roomLocator || !registry.getRoom(frame.roomLocator)) && registry.stats().rooms >= (config.maxRooms ?? 1024)) { sendError(ctx, "rate_limited", "room capacity reached"); return; }
        const maxPeers = frame.maxPeers ?? config.maxPeersPerRoom;
        if (maxPeers > config.maxPeersPerRoom) {
          sendError(ctx, "invalid_params", "maxPeers exceeds server limit");
          return;
        }
        const maxExpiry = now + config.roomTtlSeconds * 1000;
        if (frame.inviteExpiresAt <= now || frame.inviteExpiresAt > maxExpiry) {
          sendError(ctx, "invalid_params", "inviteExpiresAt out of range");
          return;
        }
        const result = registry.registerHost(
          {
            roomLocator: frame.roomLocator,
            inviteTokenHash: frame.inviteTokenHash,
            inviteExpiresAt: frame.inviteExpiresAt,
            hostFingerprint: frame.hostFingerprint,
            recoverySecret: frame.recoverySecret,
            sessionName: frame.sessionName,
            maxPeers,
            connectionId: ctx.connectionId,
            ttlSeconds: config.roomTtlSeconds,
          },
          now,
        );
        if (!result.ok) {
          sendError(ctx, "room_claimed", "room is claimed by a different host");
          return;
        }
        ctx.hasHostedOrJoined = true;
        logger.info("host.registered", {
          connectionId: ctx.connectionId,
          roomLocator: result.roomLocator,
        });
        send(ctx, {
          v: 1,
          type: "host.registered",
          roomLocator: result.roomLocator,
          hostPeerId: result.hostPeerId,
          expiresAt: result.expiresAt,
        });
        return;
      }
      case "host.heartbeat": {
        const result = registry.heartbeat(
          ctx.connectionId,
          now,
          config.roomTtlSeconds,
        );
        if (!result.ok) {
          sendError(ctx, "not_authorized", "not a registered host");
          return;
        }
        send(ctx, {
          v: 1,
          type: "host.heartbeat.ack",
          expiresAt: result.expiresAt,
        });
        return;
      }
      case "host.rotate_invite": {
        if (frame.inviteExpiresAt <= now || frame.inviteExpiresAt > now + config.roomTtlSeconds * 1000) { sendError(ctx, "invalid_params", "inviteExpiresAt out of range"); return; }
        const result = registry.rotateInvite(
          ctx.connectionId,
          frame.inviteTokenHash,
          frame.inviteExpiresAt,
        );
        if (!result.ok) {
          sendError(ctx, "not_authorized", "not a registered host");
          return;
        }
        roomAttemptCounter.reset(result.roomLocator);
        send(ctx, { v: 1, type: "host.invite_rotated" });
        return;
      }
      case "host.revoke_invite": {
        const result = registry.revokeInvite(ctx.connectionId);
        if (!result.ok) {
          sendError(ctx, "not_authorized", "not a registered host");
          return;
        }
        send(ctx, { v: 1, type: "host.invite_revoked" });
        return;
      }
      case "host.join_decision": {
        const result = registry.decideJoin(
          ctx.connectionId,
          frame.guestPeerId,
          frame.accept,
          now,
        );
        if (!result.ok) {
          sendError(ctx, "invalid_params", "no such pending guest");
          return;
        }
        const guestCtx = connections.get(result.peer.connectionId);
        if (result.accepted) {
          if (guestCtx) {
            send(guestCtx, {
              v: 1,
              type: "join.accepted",
              roomLocator: result.room.roomLocator,
              hostPeerId: result.room.hostPeerId,
              peerId: result.peer.peerId,
            });
          }
          broadcastTo(
            [...result.room.peers.values()]
              .filter((p) => p.accepted)
              .map((p) => p.connectionId),
            { v: 1, type: "room.roster", peers: registry.getRoster(result.room.roomLocator) },
          );
        } else {
          if (guestCtx) {
            send(guestCtx, {
              v: 1,
              type: "join.rejected",
              reason: "host_declined",
            });
          }
        }
        return;
      }
      case "guest.join": {
        if (registry.isConnectionActive(ctx.connectionId)) {
          sendError(ctx, "already_joined", "connection already hosts or joined a room");
          return;
        }
        if (
          roomAttemptCounter.isBlocked(frame.roomLocator, now) ||
          ipAttemptCounter.isBlocked(ctx.ip, now)
        ) {
          send(ctx, {
            v: 1,
            type: "join.rejected",
            reason: "too_many_attempts",
          });
          return;
        }
        const result = registry.attemptGuestJoin(
          {
            roomLocator: frame.roomLocator,
            inviteToken: frame.inviteToken,
            displayName: frame.displayName,
            peerFingerprint: frame.peerFingerprint,
            connectionId: ctx.connectionId,
          },
          now,
        );
        if (!result.ok) {
          // Only credential-related failures count against the
          // brute-force budget; room_full is not a guessing signal.
          if (result.reason !== "room_full") {
            roomAttemptCounter.recordFailure(frame.roomLocator, now);
            ipAttemptCounter.recordFailure(ctx.ip, now);
          }
          const reason: JoinRejectReason = result.reason;
          logger.info("guest.join_rejected", {
            connectionId: ctx.connectionId,
            roomLocator: truncateRoomLocator(frame.roomLocator),
            reason,
          });
          send(ctx, { v: 1, type: "join.rejected", reason });
          return;
        }
        ctx.hasHostedOrJoined = true;
        logger.info("guest.join_pending", {
          connectionId: ctx.connectionId,
          roomLocator: truncateRoomLocator(result.roomLocator),
          peerId: result.peerId,
        });
        send(ctx, {
          v: 1,
          type: "join.pending",
          hostPeerId: result.hostPeerId,
          peerId: result.peerId,
        });
        const hostCtx = connections.get(result.hostConnectionId);
        if (hostCtx) {
          send(hostCtx, {
            v: 1,
            type: "room.join_request",
            guestPeerId: result.peerId,
            displayName: frame.displayName,
            peerFingerprint: frame.peerFingerprint,
          });
        } else {
          send(ctx, { v: 1, type: "join.rejected", reason: "host_unavailable" });
        }
        return;
      }
      case "signal.relay": {
        if (!ctx.relayBucket.take(1)) {
          sendError(ctx, "rate_limited", "relay rate exceeded");
          strikeAndMaybeClose(ctx);
          return;
        }
        if (!isPeerId(frame.toPeerId)) {
          sendError(ctx, "invalid_params", "invalid toPeerId");
          return;
        }
        const lookup = registry.relayLookup(ctx.connectionId, frame.toPeerId);
        if (!lookup.ok) {
          sendError(ctx, lookup.code, "cannot relay to that peer");
          return;
        }
        const targetCtx = connections.get(lookup.toConnectionId);
        if (!targetCtx) {
          sendError(ctx, "peer_unreachable", "target peer is not connected");
          return;
        }
        send(targetCtx, {
          v: 1,
          type: "signal.deliver",
          fromPeerId: lookup.fromPeerId,
          payload: frame.payload,
        });
        return;
      }
      case "peer.leave": {
        const effect = registry.leaveAsGuest(ctx.connectionId, now);
        applyDisconnectEffect(effect);
        return;
      }
      case "room.close": {
        const effect = registry.closeRoomAsHost(ctx.connectionId, "host_closed");
        applyDisconnectEffect(effect);
        return;
      }
      case "turn.credentials": {
        const state = registry.getConnectionState(ctx.connectionId);
        const room = state && registry.getRoom(state.roomLocator);
        const peer = state && room?.peers.get(state.peerId);
        if (!peer?.accepted || peer.connectionId !== ctx.connectionId || !room || room.expiresAtMs <= now) { sendError(ctx, "not_authorized", "admitted membership required"); return; }
        const expiresAt = Math.floor(now / 1000) + (config.turnTtlSeconds ?? 600);
        const username = `${expiresAt}:${peer.peerId}`;
        const iceServers = config.turnSecret && config.turnUrls?.length ? [{ urls: config.turnUrls, username, credential: createHmac("sha1", config.turnSecret).update(username).digest("base64") }] : [];
        send(ctx, { v: 1, type: "turn.credentials", iceServers, expiresAt: expiresAt * 1000 });
        return;
      }
      case "ping": {
        send(ctx, { v: 1, type: "pong", serverTimeMs: Date.now() });
        return;
      }
      default: {
        sendError(ctx, "unknown_type", "unrecognized frame type");
      }
    }
  }

  // --- Liveness pings: terminate sockets that miss 2 pongs. ---
  const heartbeatInterval = setInterval(() => {
    for (const ctx of connections.values()) {
      if (!ctx.isAlive) {
        ctx.missedPongs += 1;
        if (ctx.missedPongs >= 2) {
          ctx.socket.terminate();
          continue;
        }
      }
      ctx.isAlive = false;
      ctx.socket.ping();
    }
  }, 30_000);

  // --- Room TTL sweeper. ---
  const sweepInterval = setInterval(() => {
    const nowMs = Date.now();
    const expired = registry.sweepExpiredRooms(nowMs);
    for (const room of expired) {
      broadcastTo(room.memberConnectionIds, {
        v: 1,
        type: "signaling.unavailable",
        reason: "expired",
      });
      for (const cid of room.memberConnectionIds) {
        connections.get(cid)?.socket.close(1000, "room expired");
      }
      logger.info("room.expired", {
        roomLocator: truncateRoomLocator(room.roomLocator),
      });
    }
    roomAttemptCounter.sweep(nowMs);
    ipAttemptCounter.sweep(nowMs);
  }, 5_000);

  async function shutdown(): Promise<void> {
    shuttingDown = true;
    clearInterval(heartbeatInterval);
    clearInterval(sweepInterval);
    const drained = registry.drainAll();
    for (const room of drained) {
      broadcastTo(room.memberConnectionIds, {
        v: 1,
        type: "signaling.unavailable",
        reason: "server_shutdown",
      });
    }
    await new Promise<void>((resolve) => setTimeout(resolve, 50));
    for (const ctx of connections.values()) {
      ctx.socket.close(1001, "server shutting down");
    }
    await close();
  }

  let closePromise: Promise<void> | undefined;
  function close(): Promise<void> {
    if (closePromise) return closePromise;
    shuttingDown = true;
    clearInterval(heartbeatInterval);
    clearInterval(sweepInterval);
    for (const ctx of connections.values()) ctx.socket.terminate();
    registry.drainAll();
    closePromise = new Promise((resolve, reject) => {
      wss.close(() => {
        httpServer.close((err) => {
          if (err && (err as NodeJS.ErrnoException).code !== "ERR_SERVER_NOT_RUNNING") reject(err);
          else resolve();
        });
        httpServer.closeAllConnections();
      });
    });
    return closePromise;
  }

  return {
    httpServer,
    wss,
    close,
    shutdown,
    address: () => {
      const addr = httpServer.address();
      if (addr && typeof addr === "object") {
        return { port: addr.port, host: config.host };
      }
      return { port: config.port, host: config.host };
    },
  };
}

export function listen(server: JunctionServer, port: number, host: string): Promise<void> {
  return new Promise((resolve, reject) => {
    server.httpServer.once("error", reject);
    server.httpServer.listen(port, host, () => resolve());
  });
}
