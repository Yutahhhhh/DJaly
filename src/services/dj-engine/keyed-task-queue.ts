/** Serialize metadata/load completion against grid saves for the same track. */
export class KeyedTaskQueue {
  private tails = new Map<number, Promise<unknown>>();
  run<T>(key: number, task: () => Promise<T>): Promise<T> {
    const result = (this.tails.get(key) ?? Promise.resolve()).then(task, task);
    const tail = result.then(() => undefined, () => undefined);
    this.tails.set(key, tail);
    void tail.then(() => { if (this.tails.get(key) === tail) this.tails.delete(key); });
    return result;
  }
}
