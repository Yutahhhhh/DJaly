type Pending<T> = { value: T; promise: Promise<void>; resolve: () => void; reject: (error: unknown) => void };

/** One RPC in flight and one replaceable target, never an event-sized backlog. */
export class LatestCommandQueue<T> {
  private active = false;
  private pending: Pending<T> | null = null;
  private readonly send: (value: T) => Promise<unknown>;
  private readonly continuePendingOnError: boolean;

  constructor(send: (value: T) => Promise<unknown>, continuePendingOnError = false) {
    this.send = send;
    this.continuePendingOnError = continuePendingOnError;
  }

  enqueue(value: T): Promise<void> {
    if (this.pending) { this.pending.value = value; return this.pending.promise; }
    let resolve!: () => void;
    let reject!: (error: unknown) => void;
    const promise = new Promise<void>((ok, fail) => { resolve = ok; reject = fail; });
    const item = { value, promise, resolve, reject };
    if (this.active) this.pending = item;
    else this.start(item);
    return promise;
  }

  clear() { this.pending?.resolve(); this.pending = null; }

  private start(item: Pending<T>) {
    this.active = true;
    void Promise.resolve().then(() => this.send(item.value)).then(() => {
      this.active = false;
      const next = this.pending; this.pending = null;
      if (next) this.start(next);
      item.resolve();
    }, (error: unknown) => {
      this.active = false;
      if (this.continuePendingOnError && this.pending) {
        const next = this.pending; this.pending = null;
        this.start(next);
        item.reject(error);
        return;
      }
      this.pending?.reject(error); this.pending = null;
      item.reject(error);
    });
  }
}
