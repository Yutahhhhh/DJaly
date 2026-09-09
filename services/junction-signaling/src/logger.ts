// Structured, leveled logger with a redact() helper.
//
// Hard rule: never log raw invite tokens, invite hashes-as-secrets-adjacent
// material, or arbitrary relay payloads. Only log `type`, a truncated
// `roomLocator`, `peerId`, and coarse outcomes.

export type LogLevel = "debug" | "info" | "warn" | "error";

const LEVEL_ORDER: Record<LogLevel, number> = {
  debug: 10,
  info: 20,
  warn: 30,
  error: 40,
};

export interface LogFields {
  [key: string]: unknown;
}

export interface Logger {
  debug(msg: string, fields?: LogFields): void;
  info(msg: string, fields?: LogFields): void;
  warn(msg: string, fields?: LogFields): void;
  error(msg: string, fields?: LogFields): void;
}

/**
 * Redacts known-sensitive keys and shortens identifiers that could
 * otherwise be used to reconstruct secrets or dox room locators in logs.
 * Deliberately conservative: unknown keys pass through since values must
 * already have been pre-filtered by the caller (only safe fields are
 * passed into the logger to begin with).
 */
export function redact(fields: LogFields): LogFields {
  const SENSITIVE_KEYS = new Set([
    "inviteToken",
    "invitetoken",
    "rawtoken",
    "token",
    "payload",
    "inviteTokenHash",
    "password",
    "secret",
    "recoverysecret",
    "recoverysecrethash",
    "credential",
    "turnsecret",
    "invitetokenhash",
  ]);

  const out: LogFields = {};
  for (const [key, value] of Object.entries(fields)) {
    if (SENSITIVE_KEYS.has(key) || SENSITIVE_KEYS.has(key.toLowerCase())) {
      out[key] = "[redacted]";
      continue;
    }
    if (key === "roomLocator" && typeof value === "string") {
      out[key] = truncateRoomLocator(value);
      continue;
    }
    out[key] = value;
  }
  return out;
}

export function truncateRoomLocator(roomLocator: string): string {
  return `${roomLocator.slice(0, 8)}…`;
}

export interface LoggerOptions {
  level: LogLevel;
  /** Override the sink for testing; defaults to console. */
  write?: (line: string) => void;
}

export function createLogger(options: LoggerOptions): Logger {
  const { level, write = (line: string) => console.log(line) } = options;
  const threshold = LEVEL_ORDER[level];

  function emit(lvl: LogLevel, msg: string, fields?: LogFields): void {
    if (LEVEL_ORDER[lvl] < threshold) return;
    const safeFields = fields ? redact(fields) : {};
    const record = {
      ts: new Date().toISOString(),
      level: lvl,
      msg,
      ...safeFields,
    };
    write(JSON.stringify(record));
  }

  return {
    debug: (msg, fields) => emit("debug", msg, fields),
    info: (msg, fields) => emit("info", msg, fields),
    warn: (msg, fields) => emit("warn", msg, fields),
    error: (msg, fields) => emit("error", msg, fields),
  };
}
