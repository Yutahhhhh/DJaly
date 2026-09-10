// plumdeck Junction signaling wire protocol v1.
//
// Every frame is a single JSON object with {v:1, type:<name>, ...}.
// This module is pure: no ws/net imports, only frame shapes + validators.

export const PROTOCOL_VERSION = 1 as const;

export type Role = "host" | "guest";

export type ErrorCode =
  | "bad_frame"
  | "frame_too_large"
  | "unknown_type"
  | "invalid_params"
  | "not_authorized"
  | "already_registered"
  | "already_joined"
  | "room_claimed"
  | "unknown_room"
  | "peer_unreachable"
  | "rate_limited"
  | "not_ready";

export type JoinRejectReason =
  | "invalid_invite"
  | "expired_invite"
  | "revoked_invite"
  | "unknown_room"
  | "room_full"
  | "too_many_attempts"
  | "host_declined"
  | "host_unavailable";

export type RoomCloseReason = "host_closed";

// ---- Client -> server frames ----

export interface HostRegisterFrame {
  v: 1;
  type: "host.register";
  roomLocator?: string;
  inviteTokenHash: string;
  inviteExpiresAt: number;
  hostFingerprint: string;
  recoverySecret: string;
  sessionName: string;
  maxPeers?: number;
}

export interface HostHeartbeatFrame {
  v: 1;
  type: "host.heartbeat";
}

export interface HostRotateInviteFrame {
  v: 1;
  type: "host.rotate_invite";
  inviteTokenHash: string;
  inviteExpiresAt: number;
}

export interface HostRevokeInviteFrame {
  v: 1;
  type: "host.revoke_invite";
}

export interface HostJoinDecisionFrame {
  v: 1;
  type: "host.join_decision";
  guestPeerId: string;
  accept: boolean;
  reason?: string;
}

export interface GuestJoinFrame {
  v: 1;
  type: "guest.join";
  roomLocator: string;
  inviteToken: string;
  displayName: string;
  peerFingerprint: string;
}

export interface SignalRelayFrame {
  v: 1;
  type: "signal.relay";
  toPeerId: string;
  payload: unknown;
}

export interface PeerLeaveFrame {
  v: 1;
  type: "peer.leave";
  reason?: string;
}

export interface RoomCloseFrame {
  v: 1;
  type: "room.close";
}

export interface PingFrame {
  v: 1;
  type: "ping";
}

export type ClientFrame =
  | HostRegisterFrame
  | HostHeartbeatFrame
  | HostRotateInviteFrame
  | HostRevokeInviteFrame
  | HostJoinDecisionFrame
  | GuestJoinFrame
  | SignalRelayFrame
  | PeerLeaveFrame
  | RoomCloseFrame
  | PingFrame
  | { v: 1; type: "turn.credentials" };

// ---- Server -> client frames ----

export interface ServerHelloFrame {
  v: 1;
  type: "server.hello";
  protocolVersion: 1;
  serverVersion: string;
  limits: {
    maxFrameBytes: number;
    maxRoomTtlSeconds: number;
    maxPeersPerRoom: number;
    relayRatePerSecond: number;
    joinAttemptsPerRoomPerMinute: number;
  };
}

export interface HostRegisteredFrame {
  v: 1;
  type: "host.registered";
  roomLocator: string;
  hostPeerId: string;
  expiresAt: number;
}

export interface HostHeartbeatAckFrame {
  v: 1;
  type: "host.heartbeat.ack";
  expiresAt: number;
}

export interface HostInviteRotatedFrame {
  v: 1;
  type: "host.invite_rotated";
}

export interface HostInviteRevokedFrame {
  v: 1;
  type: "host.invite_revoked";
}

export interface JoinPendingFrame {
  v: 1;
  type: "join.pending";
  hostPeerId: string;
  peerId: string;
}

export interface RoomJoinRequestFrame {
  v: 1;
  type: "room.join_request";
  guestPeerId: string;
  displayName: string;
  peerFingerprint: string;
}

export interface JoinRejectedFrame {
  v: 1;
  type: "join.rejected";
  reason: JoinRejectReason;
}

export interface JoinAcceptedFrame {
  v: 1;
  type: "join.accepted";
  roomLocator: string;
  hostPeerId: string;
  peerId: string;
}

export interface SignalDeliverFrame {
  v: 1;
  type: "signal.deliver";
  fromPeerId: string;
  payload: unknown;
}

export interface PeerGoneFrame {
  v: 1;
  type: "peer.gone";
  peerId: string;
  reason: string;
}

export interface RoomClosedFrame {
  v: 1;
  type: "room.closed";
  reason: RoomCloseReason;
}

export interface RoomRosterEntry {
  peerId: string;
  displayName: string;
  role: Role;
  acceptedAt: number;
}

export interface RoomRosterFrame {
  v: 1;
  type: "room.roster";
  peers: RoomRosterEntry[];
}

export interface ErrorFrame {
  v: 1;
  type: "error";
  code: ErrorCode;
  message: string;
}

export interface PongFrame {
  v: 1;
  type: "pong";
  serverTimeMs: number;
}

export type ServerFrame =
  | ServerHelloFrame
  | HostRegisteredFrame
  | HostHeartbeatAckFrame
  | HostInviteRotatedFrame
  | HostInviteRevokedFrame
  | JoinPendingFrame
  | RoomJoinRequestFrame
  | JoinRejectedFrame
  | JoinAcceptedFrame
  | SignalDeliverFrame
  | PeerGoneFrame
  | RoomClosedFrame
  | RoomRosterFrame
  | ErrorFrame
  | PongFrame
  | { v: 1; type: "signaling.unavailable"; reason: string }
  | { v: 1; type: "turn.credentials"; iceServers: { urls: string[]; username: string; credential: string }[]; expiresAt: number };

// ---- Validators ----

const ROOM_LOCATOR_RE = /^[a-f0-9]{32}$/;
const HOST_FINGERPRINT_RE = /^[A-Za-z0-9:_.\-]{16,128}$/;
const INVITE_TOKEN_RE = /^[A-Za-z0-9_-]{22,128}$/;
const INVITE_HASH_RE = /^[a-f0-9]{64}$/;
const PEER_ID_RE = /^[a-f0-9]{24}$/;
const CONTROL_CHARS_RE = buildControlCharsRegex();
function buildControlCharsRegex(): RegExp {
  const ranges: string[] = [];
  for (let i = 0; i <= 0x1f; i++) ranges.push(String.fromCharCode(i));
  ranges.push(String.fromCharCode(0x7f));
  const escaped = ranges.join("");
  return new RegExp("[" + escaped.replace(/[\\\]^-]/g, "\\$&") + "]", "g");
}

export function isRoomLocator(value: unknown): value is string {
  return typeof value === "string" && ROOM_LOCATOR_RE.test(value);
}

export function isHostFingerprint(value: unknown): value is string {
  return typeof value === "string" && HOST_FINGERPRINT_RE.test(value);
}

export function isInviteToken(value: unknown): value is string {
  return typeof value === "string" && INVITE_TOKEN_RE.test(value);
}

export function isInviteTokenHash(value: unknown): value is string {
  return typeof value === "string" && INVITE_HASH_RE.test(value);
}

export function isPeerId(value: unknown): value is string {
  return typeof value === "string" && PEER_ID_RE.test(value);
}

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isFiniteNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

/**
 * Sanitizes a display name: trims, strips control/newline characters, and
 * enforces the 1..40 char length bound. Returns null if invalid.
 */
export function sanitizeDisplayName(raw: unknown): string | null {
  if (typeof raw !== "string") return null;
  const trimmed = raw.trim();
  if (trimmed.length < 1 || trimmed.length > 40) return null;
  // eslint-disable-next-line no-control-regex
  const stripped = trimmed.replace(CONTROL_CHARS_RE, "");
  const finalName = stripped.trim();
  if (finalName.length < 1 || finalName.length > 40) return null;
  return finalName;
}

export type ParseResult<T> =
  | { ok: true; frame: T }
  | { ok: false; error: string };

/**
 * Parses and validates a raw text frame into a typed ClientFrame.
 * Does not enforce frame size — callers must check byte length first.
 */
export function parseClientFrame(raw: string): ParseResult<ClientFrame> {
  let json: unknown;
  try {
    json = JSON.parse(raw);
  } catch {
    return { ok: false, error: "invalid JSON" };
  }
  if (!isPlainObject(json)) {
    return { ok: false, error: "frame must be a JSON object" };
  }
  if (json.v !== 1) {
    return { ok: false, error: "unsupported or missing protocol version" };
  }
  if (typeof json.type !== "string") {
    return { ok: false, error: "missing type" };
  }

  switch (json.type) {
    case "host.register": {
      if (
        json.roomLocator !== undefined &&
        !isRoomLocator(json.roomLocator)
      ) {
        return { ok: false, error: "invalid roomLocator" };
      }
      if (!isInviteTokenHash(json.inviteTokenHash)) {
        return { ok: false, error: "invalid inviteTokenHash" };
      }
      if (!isFiniteNumber(json.inviteExpiresAt)) {
        return { ok: false, error: "invalid inviteExpiresAt" };
      }
      if (!isInviteToken(json.recoverySecret)) return { ok: false, error: "invalid recoverySecret" };
      if (!isHostFingerprint(json.hostFingerprint)) {
        return { ok: false, error: "invalid hostFingerprint" };
      }
      if (
        typeof json.sessionName !== "string" ||
        json.sessionName.trim().length < 1 ||
        json.sessionName.length > 80
      ) {
        return { ok: false, error: "invalid sessionName" };
      }
      if (
        json.maxPeers !== undefined &&
        (!isFiniteNumber(json.maxPeers) ||
          !Number.isInteger(json.maxPeers) ||
          json.maxPeers < 1 ||
          json.maxPeers > 256)
      ) {
        return { ok: false, error: "invalid maxPeers" };
      }
      return {
        ok: true,
        frame: {
          v: 1,
          type: "host.register",
          roomLocator: json.roomLocator as string | undefined,
          inviteTokenHash: json.inviteTokenHash,
          inviteExpiresAt: json.inviteExpiresAt,
          hostFingerprint: json.hostFingerprint,
          recoverySecret: json.recoverySecret,
          sessionName: json.sessionName,
          maxPeers: json.maxPeers as number | undefined,
        },
      };
    }
    case "turn.credentials":
      return { ok: true, frame: { v: 1, type: "turn.credentials" } };
    case "host.heartbeat":
      return { ok: true, frame: { v: 1, type: "host.heartbeat" } };
    case "host.rotate_invite": {
      if (!isInviteTokenHash(json.inviteTokenHash)) {
        return { ok: false, error: "invalid inviteTokenHash" };
      }
      if (!isFiniteNumber(json.inviteExpiresAt)) {
        return { ok: false, error: "invalid inviteExpiresAt" };
      }
      return {
        ok: true,
        frame: {
          v: 1,
          type: "host.rotate_invite",
          inviteTokenHash: json.inviteTokenHash,
          inviteExpiresAt: json.inviteExpiresAt,
        },
      };
    }
    case "host.revoke_invite":
      return { ok: true, frame: { v: 1, type: "host.revoke_invite" } };
    case "host.join_decision": {
      if (!isPeerId(json.guestPeerId)) {
        return { ok: false, error: "invalid guestPeerId" };
      }
      if (typeof json.accept !== "boolean") {
        return { ok: false, error: "invalid accept" };
      }
      if (json.reason !== undefined && typeof json.reason !== "string") {
        return { ok: false, error: "invalid reason" };
      }
      return {
        ok: true,
        frame: {
          v: 1,
          type: "host.join_decision",
          guestPeerId: json.guestPeerId,
          accept: json.accept,
          reason: json.reason as string | undefined,
        },
      };
    }
    case "guest.join": {
      if (!isRoomLocator(json.roomLocator)) {
        return { ok: false, error: "invalid roomLocator" };
      }
      if (!isInviteToken(json.inviteToken)) {
        return { ok: false, error: "invalid inviteToken" };
      }
      const displayName = sanitizeDisplayName(json.displayName);
      if (displayName === null) {
        return { ok: false, error: "invalid displayName" };
      }
      if (
        typeof json.peerFingerprint !== "string" ||
        json.peerFingerprint.length < 1 ||
        json.peerFingerprint.length > 128
      ) {
        return { ok: false, error: "invalid peerFingerprint" };
      }
      return {
        ok: true,
        frame: {
          v: 1,
          type: "guest.join",
          roomLocator: json.roomLocator,
          inviteToken: json.inviteToken,
          displayName,
          peerFingerprint: json.peerFingerprint,
        },
      };
    }
    case "signal.relay": {
      if (!isPeerId(json.toPeerId)) {
        return { ok: false, error: "invalid toPeerId" };
      }
      if (!("payload" in json)) {
        return { ok: false, error: "missing payload" };
      }
      return {
        ok: true,
        frame: {
          v: 1,
          type: "signal.relay",
          toPeerId: json.toPeerId,
          payload: json.payload,
        },
      };
    }
    case "peer.leave": {
      if (json.reason !== undefined && typeof json.reason !== "string") {
        return { ok: false, error: "invalid reason" };
      }
      return {
        ok: true,
        frame: {
          v: 1,
          type: "peer.leave",
          reason: json.reason as string | undefined,
        },
      };
    }
    case "room.close":
      return { ok: true, frame: { v: 1, type: "room.close" } };
    case "ping":
      return { ok: true, frame: { v: 1, type: "ping" } };
    default:
      return { ok: false, error: `unknown type: ${json.type}` };
  }
}
