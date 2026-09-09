// RoomRegistry: in-memory room/peer state, TTL sweeping, invite
// verification and admission bookkeeping. Deliberately has no `ws` or
// `http` import — it is pure domain logic driven entirely by explicit
// inputs (connectionId strings, timestamps) so it can be unit tested
// without any network layer.

import { randomBytes, timingSafeEqual, createHash } from "node:crypto";
import type { Role } from "./protocol.js";

export function generateRoomLocator(): string {
  return randomBytes(16).toString("hex");
}

export function generatePeerId(): string {
  return randomBytes(12).toString("hex");
}

export function hashInviteToken(rawToken: string): string {
  return createHash("sha256").update(rawToken, "utf8").digest("hex");
}

function safeHashEquals(candidateHex: string, storedHex: string): boolean {
  if (candidateHex.length !== storedHex.length) return false;
  const a = Buffer.from(candidateHex, "hex");
  const b = Buffer.from(storedHex, "hex");
  if (a.length !== b.length) return false;
  return timingSafeEqual(a, b);
}

export interface PeerRecord {
  peerId: string;
  connectionId: string;
  role: Role;
  displayName: string;
  peerFingerprint: string;
  accepted: boolean;
  admissionInviteHash?: string;
  acceptedAtMs: number | null;
}

export interface Room {
  roomLocator: string;
  hostPeerId: string;
  hostConnectionId: string;
  hostFingerprint: string;
  recoverySecretHash: string;
  sessionName: string;
  maxPeers: number;
  inviteTokenHash: string | null;
  inviteExpiresAt: number;
  createdAtMs: number;
  expiresAtMs: number;
  peers: Map<string, PeerRecord>;
}

interface ConnectionState {
  roomLocator: string;
  peerId: string;
  role: Role;
}

export interface RegisterHostInput {
  roomLocator?: string;
  inviteTokenHash: string;
  inviteExpiresAt: number;
  hostFingerprint: string;
  recoverySecret: string;
  sessionName: string;
  maxPeers: number;
  connectionId: string;
  ttlSeconds: number;
}

export type RegisterHostResult =
  | {
      ok: true;
      room: Room;
      roomLocator: string;
      hostPeerId: string;
      expiresAt: number;
    }
  | { ok: false; code: "room_claimed" };

export type GuestJoinReason =
  | "invalid_invite"
  | "expired_invite"
  | "revoked_invite"
  | "room_full"
  | "host_unavailable";

export interface GuestJoinInput {
  roomLocator: string;
  inviteToken: string;
  displayName: string;
  peerFingerprint: string;
  connectionId: string;
}

export type GuestJoinResult =
  | {
      ok: true;
      peerId: string;
      hostPeerId: string;
      hostConnectionId: string;
      roomLocator: string;
    }
  | { ok: false; reason: GuestJoinReason };

export interface RosterEntry {
  peerId: string;
  displayName: string;
  role: Role;
  acceptedAt: number;
}

export type RelayLookupResult =
  | { ok: true; fromPeerId: string; toConnectionId: string }
  | { ok: false; code: "not_authorized" | "not_ready" | "peer_unreachable" | "unknown_room" };

export interface DisconnectEffectGuestLeft {
  kind: "guest_left";
  roomLocator: string;
  removedPeerId: string;
  remainingConnectionIds: string[];
  roster: RosterEntry[];
}

export interface DisconnectEffectRoomClosed {
  kind: "room_closed";
  roomLocator: string;
  reason: "host_closed";
  memberConnectionIds: string[];
}

export type DisconnectEffect =
  | { kind: "host_unavailable"; memberConnectionIds: string[] }
  | { kind: "none" }
  | DisconnectEffectGuestLeft
  | DisconnectEffectRoomClosed;

export interface ExpiredRoomEffect {
  roomLocator: string;
  memberConnectionIds: string[];
}

export class RoomRegistry {
  private readonly rooms = new Map<string, Room>();
  private readonly connections = new Map<string, ConnectionState>();

  isConnectionActive(connectionId: string): boolean {
    return this.connections.has(connectionId);
  }

  getConnectionState(connectionId: string): ConnectionState | undefined {
    return this.connections.get(connectionId);
  }

  getRoom(roomLocator: string): Room | undefined {
    return this.rooms.get(roomLocator);
  }

  private isLive(room: Room, nowMs: number): boolean {
    return room.expiresAtMs > nowMs;
  }

  registerHost(input: RegisterHostInput, nowMs: number): RegisterHostResult {
    const roomLocator = input.roomLocator ?? generateRoomLocator();
    const existing = this.rooms.get(roomLocator);

    if (existing && this.isLive(existing, nowMs)) {
      if (existing.hostFingerprint !== input.hostFingerprint || !safeHashEquals(hashInviteToken(input.recoverySecret), existing.recoverySecretHash)) {
        return { ok: false, code: "room_claimed" };
      }
      this.connections.delete(existing.hostConnectionId);
      existing.hostConnectionId = input.connectionId;
      existing.inviteTokenHash = input.inviteTokenHash;
      existing.inviteExpiresAt = input.inviteExpiresAt;
      existing.sessionName = input.sessionName;
      existing.maxPeers = input.maxPeers;
      existing.expiresAtMs = nowMs + input.ttlSeconds * 1000;
      const hostPeer = existing.peers.get(existing.hostPeerId);
      if (hostPeer) {
        hostPeer.connectionId = input.connectionId;
        hostPeer.displayName = input.sessionName;
      }
      this.connections.set(input.connectionId, {
        roomLocator,
        peerId: existing.hostPeerId,
        role: "host",
      });
      return {
        ok: true,
        room: existing,
        roomLocator,
        hostPeerId: existing.hostPeerId,
        expiresAt: existing.expiresAtMs,
      };
    }

    if (existing) {
      for (const peer of existing.peers.values()) this.connections.delete(peer.connectionId);
    }
    // Stable across discovery restarts while remaining scoped to this room
    // and the native DTLS identity. Registration still requires the recovery
    // secret while the room exists; clients verify the actual DTLS identity.
    const hostPeerId = createHash("sha256").update(`${roomLocator}\0${input.hostFingerprint}`).digest("hex").slice(0, 24);
    const expiresAtMs = nowMs + input.ttlSeconds * 1000;
    const room: Room = {
      roomLocator,
      hostPeerId,
      hostConnectionId: input.connectionId,
      hostFingerprint: input.hostFingerprint,
      recoverySecretHash: hashInviteToken(input.recoverySecret),
      sessionName: input.sessionName,
      maxPeers: input.maxPeers,
      inviteTokenHash: input.inviteTokenHash,
      inviteExpiresAt: input.inviteExpiresAt,
      createdAtMs: nowMs,
      expiresAtMs,
      peers: new Map([
        [
          hostPeerId,
          {
            peerId: hostPeerId,
            connectionId: input.connectionId,
            role: "host",
            displayName: input.sessionName,
            peerFingerprint: input.hostFingerprint,
            accepted: true,
            acceptedAtMs: nowMs,
          },
        ],
      ]),
    };
    this.rooms.set(roomLocator, room);
    this.connections.set(input.connectionId, {
      roomLocator,
      peerId: hostPeerId,
      role: "host",
    });
    return { ok: true, room, roomLocator, hostPeerId, expiresAt: expiresAtMs };
  }

  heartbeat(
    connectionId: string,
    nowMs: number,
    ttlSeconds: number,
  ): { ok: true; expiresAt: number } | { ok: false } {
    const state = this.connections.get(connectionId);
    if (!state || state.role !== "host") return { ok: false };
    const room = this.rooms.get(state.roomLocator);
    if (!room) return { ok: false };
    room.expiresAtMs = nowMs + ttlSeconds * 1000;
    return { ok: true, expiresAt: room.expiresAtMs };
  }

  rotateInvite(
    connectionId: string,
    inviteTokenHash: string,
    inviteExpiresAt: number,
  ): { ok: true; roomLocator: string } | { ok: false } {
    const state = this.connections.get(connectionId);
    if (!state || state.role !== "host") return { ok: false };
    const room = this.rooms.get(state.roomLocator);
    if (!room) return { ok: false };
    room.inviteTokenHash = inviteTokenHash;
    room.inviteExpiresAt = inviteExpiresAt;
    return { ok: true, roomLocator: room.roomLocator };
  }

  revokeInvite(connectionId: string): { ok: true } | { ok: false } {
    const state = this.connections.get(connectionId);
    if (!state || state.role !== "host") return { ok: false };
    const room = this.rooms.get(state.roomLocator);
    if (!room) return { ok: false };
    room.inviteTokenHash = null;
    return { ok: true };
  }

  attemptGuestJoin(input: GuestJoinInput, nowMs: number): GuestJoinResult {
    const room = this.rooms.get(input.roomLocator);
    if (!room || !this.isLive(room, nowMs)) {
      // Deliberately folded into invalid_invite: never reveal whether the
      // room exists.
      return { ok: false, reason: "invalid_invite" };
    }
    if (room.inviteTokenHash === null) {
      return { ok: false, reason: "revoked_invite" };
    }
    if (room.inviteExpiresAt <= nowMs) {
      return { ok: false, reason: "expired_invite" };
    }
    const candidateHash = hashInviteToken(input.inviteToken);
    if (!safeHashEquals(candidateHash, room.inviteTokenHash)) {
      return { ok: false, reason: "invalid_invite" };
    }
    if (!room.hostConnectionId) return { ok: false, reason: "host_unavailable" };
    if (room.peers.size >= room.maxPeers) {
      return { ok: false, reason: "room_full" };
    }

    const peerId = generatePeerId();
    room.peers.set(peerId, {
      peerId,
      connectionId: input.connectionId,
      role: "guest",
      displayName: input.displayName,
      peerFingerprint: input.peerFingerprint,
      admissionInviteHash: room.inviteTokenHash,
      accepted: false,
      acceptedAtMs: null,
    });
    this.connections.set(input.connectionId, {
      roomLocator: room.roomLocator,
      peerId,
      role: "guest",
    });
    return {
      ok: true,
      peerId,
      hostPeerId: room.hostPeerId,
      hostConnectionId: room.hostConnectionId,
      roomLocator: room.roomLocator,
    };
  }

  decideJoin(
    hostConnectionId: string,
    guestPeerId: string,
    accept: boolean,
    nowMs: number,
  ):
    | { ok: true; accepted: true; peer: PeerRecord; room: Room }
    | { ok: true; accepted: false; peer: PeerRecord; room: Room }
    | { ok: false } {
    const hostState = this.connections.get(hostConnectionId);
    if (!hostState || hostState.role !== "host") return { ok: false };
    const room = this.rooms.get(hostState.roomLocator);
    if (!room) return { ok: false };
    const peer = room.peers.get(guestPeerId);
    if (!peer || peer.role !== "guest" || peer.accepted) return { ok: false };

    if (accept && room.inviteTokenHash !== null && peer.admissionInviteHash === room.inviteTokenHash && room.inviteExpiresAt > nowMs) {
      peer.accepted = true;
      peer.acceptedAtMs = nowMs;
      return { ok: true, accepted: true, peer, room };
    }
    room.peers.delete(guestPeerId);
    this.connections.delete(peer.connectionId);
    return { ok: true, accepted: false, peer, room };
  }

  relayLookup(fromConnectionId: string, toPeerId: string): RelayLookupResult {
    const fromState = this.connections.get(fromConnectionId);
    if (!fromState) return { ok: false, code: "not_authorized" };
    const room = this.rooms.get(fromState.roomLocator);
    if (!room) return { ok: false, code: "unknown_room" };
    const fromPeer = room.peers.get(fromState.peerId);
    if (!fromPeer || fromPeer.connectionId !== fromConnectionId) return { ok: false, code: "not_authorized" };
    if (fromPeer.role === "guest" && !fromPeer.accepted) {
      return { ok: false, code: "not_ready" };
    }
    const toPeer = room.peers.get(toPeerId);
    if (!toPeer) return { ok: false, code: "peer_unreachable" };
    if (toPeer.role === "guest" && !toPeer.accepted) {
      return { ok: false, code: "peer_unreachable" };
    }
    return {
      ok: true,
      fromPeerId: fromPeer.peerId,
      toConnectionId: toPeer.connectionId,
    };
  }

  getRoster(roomLocator: string): RosterEntry[] {
    const room = this.rooms.get(roomLocator);
    if (!room) return [];
    const out: RosterEntry[] = [];
    for (const peer of room.peers.values()) {
      if (!peer.accepted || peer.acceptedAtMs === null) continue;
      out.push({
        peerId: peer.peerId,
        displayName: peer.displayName,
        role: peer.role,
        acceptedAt: peer.acceptedAtMs,
      });
    }
    out.sort((a, b) => a.acceptedAt - b.acceptedAt);
    return out;
  }

  /** Handles an explicit `peer.leave` from a guest (host must use room.close). */
  leaveAsGuest(connectionId: string, nowMs: number): DisconnectEffect {
    const state = this.connections.get(connectionId);
    if (!state || state.role !== "guest") return { kind: "none" };
    return this.removeGuestConnection(connectionId, state, nowMs);
  }

  private removeGuestConnection(
    connectionId: string,
    state: ConnectionState,
    _nowMs: number,
  ): DisconnectEffect {
    const room = this.rooms.get(state.roomLocator);
    this.connections.delete(connectionId);
    if (!room) return { kind: "none" };
    room.peers.delete(state.peerId);
    const remainingConnectionIds: string[] = [];
    for (const peer of room.peers.values()) {
      if (peer.accepted) remainingConnectionIds.push(peer.connectionId);
    }
    return {
      kind: "guest_left",
      roomLocator: room.roomLocator,
      removedPeerId: state.peerId,
      remainingConnectionIds,
      roster: this.getRoster(room.roomLocator),
    };
  }

  /** Explicit host-initiated session termination only. */
  closeRoomAsHost(
    connectionId: string,
    reason: "host_closed",
  ): DisconnectEffect {
    const state = this.connections.get(connectionId);
    if (!state || state.role !== "host") return { kind: "none" };
    return this.destroyRoom(state.roomLocator, reason);
  }

  private destroyRoom(
    roomLocator: string,
    reason: "host_closed",
  ): DisconnectEffect {
    const room = this.rooms.get(roomLocator);
    if (!room) return { kind: "none" };
    const memberConnectionIds: string[] = [];
    for (const peer of room.peers.values()) {
      memberConnectionIds.push(peer.connectionId);
      this.connections.delete(peer.connectionId);
    }
    this.rooms.delete(roomLocator);
    return { kind: "room_closed", roomLocator, reason, memberConnectionIds };
  }

  /** Signaling loss preserves the room until its TTL, allowing host recovery. */
  handleDisconnect(connectionId: string, nowMs: number): DisconnectEffect {
    const state = this.connections.get(connectionId);
    if (!state) return { kind: "none" };
    if (state.role === "host") {
      const room = this.rooms.get(state.roomLocator);
      this.connections.delete(connectionId);
      if (!room || room.hostConnectionId !== connectionId) return { kind: "none" };
      room.hostConnectionId = "";
      const host = room.peers.get(room.hostPeerId);
      if (host) host.connectionId = "";
      return { kind: "host_unavailable", memberConnectionIds: [...room.peers.values()].map(p => p.connectionId).filter(Boolean) };
    }
    return this.removeGuestConnection(connectionId, state, nowMs);
  }

  /** Sweeps rooms whose TTL has lapsed; caller notifies each member. */
  sweepExpiredRooms(nowMs: number): ExpiredRoomEffect[] {
    const expired: ExpiredRoomEffect[] = [];
    for (const room of this.rooms.values()) {
      if (room.expiresAtMs <= nowMs) {
        const memberConnectionIds: string[] = [];
        for (const peer of room.peers.values()) {
          memberConnectionIds.push(peer.connectionId);
          this.connections.delete(peer.connectionId);
        }
        this.rooms.delete(room.roomLocator);
        expired.push({ roomLocator: room.roomLocator, memberConnectionIds });
      }
    }
    return expired;
  }

  /** For graceful shutdown: returns every live room's member connections. */
  drainAll(): ExpiredRoomEffect[] {
    const all: ExpiredRoomEffect[] = [];
    for (const room of this.rooms.values()) {
      const memberConnectionIds = Array.from(room.peers.values()).map(
        (p) => p.connectionId,
      );
      all.push({ roomLocator: room.roomLocator, memberConnectionIds });
    }
    this.rooms.clear();
    this.connections.clear();
    return all;
  }

  stats(): { rooms: number; peers: number } {
    return { rooms: this.rooms.size, peers: this.connections.size };
  }
}
