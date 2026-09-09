// Typed environment configuration loader with validation and clear errors.

import type { LogLevel } from "./logger.js";

export interface Config {
  maxRooms?: number;
  maxConnections?: number;
  maxBufferedBytes?: number;
  turnUrls?: string[];
  turnSecret?: string;
  turnTtlSeconds?: number;
  port: number;
  host: string;
  roomTtlSeconds: number;
  maxPeersPerRoom: number;
  maxFrameBytes: number;
  relayRatePerSecond: number;
  frameRatePerSecond: number;
  joinAttemptsPerMinute: number;
  allowedOrigins: string[] | null; // null => no origin restriction
  trustProxy: boolean;
  logLevel: LogLevel;
}

export class ConfigError extends Error {}

function parseIntEnv(
  name: string,
  raw: string | undefined,
  fallback: number,
): number {
  if (raw === undefined || raw === "") return fallback;
  const n = Number(raw);
  if (!Number.isFinite(n) || !Number.isInteger(n) || n <= 0) {
    throw new ConfigError(
      `${name} must be a positive integer, got: ${JSON.stringify(raw)}`,
    );
  }
  return n;
}

function parseBoolEnv(
  name: string,
  raw: string | undefined,
  fallback: boolean,
): boolean {
  if (raw === undefined || raw === "") return fallback;
  const lowered = raw.trim().toLowerCase();
  if (lowered === "true" || lowered === "1") return true;
  if (lowered === "false" || lowered === "0") return false;
  throw new ConfigError(
    `${name} must be "true" or "false", got: ${JSON.stringify(raw)}`,
  );
}

function parseLogLevel(raw: string | undefined): LogLevel {
  const fallback: LogLevel = "info";
  if (raw === undefined || raw === "") return fallback;
  const lowered = raw.trim().toLowerCase();
  if (
    lowered === "debug" ||
    lowered === "info" ||
    lowered === "warn" ||
    lowered === "error"
  ) {
    return lowered;
  }
  throw new ConfigError(
    `LOG_LEVEL must be one of debug|info|warn|error, got: ${JSON.stringify(raw)}`,
  );
}

function parseAllowedOrigins(raw: string | undefined): string[] | null {
  if (raw === undefined || raw.trim() === "") return null;
  return raw
    .split(",")
    .map((s) => s.trim())
    .filter((s) => s.length > 0);
}

export function loadConfig(
  env: NodeJS.ProcessEnv = process.env,
): Config {
  const port = parseIntEnv("PORT", env.PORT, 8787);
  const host = env.HOST && env.HOST.trim() !== "" ? env.HOST : "127.0.0.1";
  const roomTtlSeconds = parseIntEnv(
    "ROOM_TTL_SECONDS",
    env.ROOM_TTL_SECONDS,
    21600,
  );
  const maxPeersPerRoom = parseIntEnv(
    "MAX_PEERS_PER_ROOM",
    env.MAX_PEERS_PER_ROOM,
    8,
  );
  const maxFrameBytes = parseIntEnv(
    "MAX_FRAME_BYTES",
    env.MAX_FRAME_BYTES,
    65536,
  );
  const relayRatePerSecond = parseIntEnv(
    "RELAY_RATE_PER_SECOND",
    env.RELAY_RATE_PER_SECOND,
    50,
  );
  const frameRatePerSecond = parseIntEnv(
    "FRAME_RATE_PER_SECOND",
    env.FRAME_RATE_PER_SECOND,
    200,
  );
  const joinAttemptsPerMinute = parseIntEnv(
    "JOIN_ATTEMPTS_PER_MINUTE",
    env.JOIN_ATTEMPTS_PER_MINUTE,
    10,
  );
  const allowedOrigins = parseAllowedOrigins(env.ALLOWED_ORIGINS);
  const trustProxy = parseBoolEnv("TRUST_PROXY", env.TRUST_PROXY, false);
  const logLevel = parseLogLevel(env.LOG_LEVEL);

  if (maxFrameBytes > 65536) {
    throw new ConfigError(
      "MAX_FRAME_BYTES is unreasonably large (>64KiB); this service only relays small SDP/ICE blobs",
    );
  }

  const turnUrls = env.TURN_URLS?.split(",").map(s => s.trim()).filter(Boolean) ?? [];
  if (turnUrls.some(url => !/^turns?:[^\s/]+(?::\d+)?(?:\?transport=(udp|tcp))?$/.test(url))) throw new ConfigError("Invalid TURN_URLS");
  if (turnUrls.length && (!env.TURN_SECRET || env.TURN_SECRET.length < 32)) throw new ConfigError("TURN_SECRET must contain at least 32 characters");
  const turnTtlSeconds = parseIntEnv("TURN_TTL_SECONDS", env.TURN_TTL_SECONDS, 600);
  if (turnTtlSeconds > 3600) throw new ConfigError("TURN_TTL_SECONDS must be <=3600");
  if (port > 65535 || roomTtlSeconds > 604800 || maxPeersPerRoom > 256) throw new ConfigError("Port, TTL or peer limit out of range");
  return {
    maxRooms: parseIntEnv("MAX_ROOMS", env.MAX_ROOMS, 1024),
    maxConnections: parseIntEnv("MAX_CONNECTIONS", env.MAX_CONNECTIONS, 1024),
    maxBufferedBytes: parseIntEnv("MAX_BUFFERED_BYTES", env.MAX_BUFFERED_BYTES, 262144),
    turnUrls, turnSecret: env.TURN_SECRET, turnTtlSeconds,
    port,
    host,
    roomTtlSeconds,
    maxPeersPerRoom,
    maxFrameBytes,
    relayRatePerSecond,
    frameRatePerSecond,
    joinAttemptsPerMinute,
    allowedOrigins,
    trustProxy,
    logLevel,
  };
}
