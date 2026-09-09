// Pure rate-limiting primitives: token buckets for per-connection budgets,
// and sliding-window-ish attempt counters for invite brute-force protection.
// No ws/net imports; callers own timers and wiring.

export class TokenBucket {
  private tokens: number;
  private lastRefillMs: number;

  constructor(
    private readonly capacity: number,
    private readonly refillPerSecond: number,
    nowMs: number = Date.now(),
  ) {
    this.tokens = capacity;
    this.lastRefillMs = nowMs;
  }

  /** Attempts to consume `cost` tokens. Returns true if allowed. */
  take(cost: number = 1, nowMs: number = Date.now()): boolean {
    this.refill(nowMs);
    if (this.tokens < cost) return false;
    this.tokens -= cost;
    return true;
  }

  private refill(nowMs: number): void {
    const elapsedSeconds = Math.max(0, nowMs - this.lastRefillMs) / 1000;
    if (elapsedSeconds <= 0) return;
    this.tokens = Math.min(
      this.capacity,
      this.tokens + elapsedSeconds * this.refillPerSecond,
    );
    this.lastRefillMs = nowMs;
  }

  get remaining(): number {
    return this.tokens;
  }
}

/**
 * Fixed-window failed-attempt counter keyed by an arbitrary string
 * (roomLocator, IP, etc). A window resets once its duration elapses.
 */
export class AttemptCounter {
  private readonly windows = new Map<
    string,
    { count: number; windowStartMs: number }
  >();

  constructor(
    private readonly windowMs: number,
    private readonly maxAttempts: number,
    private readonly maxKeys: number = 10000,
  ) {}

  /** Records a failure; true means the budget is now exhausted. */
  recordFailure(key: string, nowMs: number = Date.now()): boolean {
    const entry = this.windows.get(key);
    if (!entry || nowMs - entry.windowStartMs >= this.windowMs) {
      if (!entry && this.windows.size >= this.maxKeys) return true;
      this.windows.set(key, { count: 1, windowStartMs: nowMs });
      return 1 >= this.maxAttempts;
    }
    entry.count += 1;
    return entry.count >= this.maxAttempts;
  }

  isBlocked(key: string, nowMs: number = Date.now()): boolean {
    const entry = this.windows.get(key);
    if (!entry) return this.windows.size >= this.maxKeys;
    if (nowMs - entry.windowStartMs >= this.windowMs) {
      this.windows.delete(key);
      return false;
    }
    return entry.count >= this.maxAttempts;
  }

  reset(key: string): void {
    this.windows.delete(key);
  }

  /** Drops windows older than their duration; call periodically to bound memory. */
  sweep(nowMs: number = Date.now()): void {
    for (const [key, entry] of this.windows) {
      if (nowMs - entry.windowStartMs >= this.windowMs) {
        this.windows.delete(key);
      }
    }
  }

  get size(): number {
    return this.windows.size;
  }
}

/**
 * Tracks "strikes" against a connection for sustained rate-limit abuse.
 * After `maxStrikes` the caller should forcibly close the socket.
 */
export class StrikeCounter {
  private strikes = 0;

  constructor(private readonly maxStrikes: number = 3) {}

  strike(): boolean {
    this.strikes += 1;
    return this.strikes >= this.maxStrikes;
  }

  get count(): number {
    return this.strikes;
  }
}
