import type { ScratchCommand } from "../../types/dj-engine.ts";

type Pending = {
  command: ScratchCommand;
  promise: Promise<void>;
  resolve: () => void;
  reject: (error: unknown) => void;
};

const MAX_ACCEPTED_GESTURES = 4;
type AcceptedGesture = { endPromise: Promise<void> | null };

function pending(command: ScratchCommand): Pending {
  let resolve!: () => void;
  let reject!: (error: unknown) => void;
  const promise = new Promise<void>((ok, fail) => { resolve = ok; reject = fail; });
  return { command, promise, resolve, reject };
}

/**
 * Serializes scratch phases without building a pointer-event-sized backlog.
 * Moves share one replaceable slot; begin/end are ordered barriers and cannot
 * be overwritten by later motion.
 */
export class ScratchCommandQueue {
  private active = false;
  private waiting: Pending[] = [];
  private accepted = new Map<string, AcceptedGesture>();
  private readonly send: (command: ScratchCommand) => Promise<unknown>;

  constructor(send: (command: ScratchCommand) => Promise<unknown>) { this.send = send; }

  enqueue(command: ScratchCommand): Promise<void> {
    const lifecycle = this.accepted.get(command.gestureId);
    if (command.phase === "begin") {
      if (lifecycle) return Promise.reject(new Error("scratch gestureId is already active"));
      if (this.accepted.size >= MAX_ACCEPTED_GESTURES) {
        return Promise.reject(new Error("scratch gesture backlog is full"));
      }
      this.accepted.set(command.gestureId, { endPromise: null });
    } else if (!lifecycle) {
      return Promise.resolve();
    } else if (command.phase === "end" && lifecycle.endPromise) {
      return lifecycle.endPromise;
    } else if (command.phase === "move" && lifecycle.endPromise) {
      return Promise.resolve();
    }
    const latest = this.waiting[this.waiting.length - 1];
    if (command.phase === "move" && latest?.command.phase === "move"
      && latest.command.gestureId === command.gestureId) {
      latest.command = command;
      return latest.promise;
    }
    const item = pending(command);
    if (command.phase === "end") this.accepted.get(command.gestureId)!.endPromise = item.promise;
    if (!this.active) this.start(item);
    else this.waiting.push(item);
    return item.promise;
  }

  /** Discard commands that have not crossed the IPC boundary. */
  clear(): void {
    for (const item of this.waiting) item.resolve();
    this.waiting = [];
    this.accepted.clear();
  }

  private start(item: Pending): void {
    this.active = true;
    void Promise.resolve().then(() => this.send(item.command)).then(() => {
      this.active = false;
      if (item.command.phase === "end") this.accepted.delete(item.command.gestureId);
      item.resolve();
      this.pump();
    }, (error: unknown) => {
      this.active = false;
      item.reject(error);
      for (const queued of this.waiting) queued.reject(error);
      this.waiting = [];
      this.accepted.clear();
    });
  }

  private pump(): void {
    const next = this.waiting.shift() ?? null;
    if (next) this.start(next);
  }
}
