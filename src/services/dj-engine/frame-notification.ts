/** Render the latest state once per frame; protocol reduction remains lossless. */
export function frameNotification<T>(
  notify: (value: T) => void,
  request: (callback: FrameRequestCallback) => number = requestAnimationFrame,
  cancel: (id: number) => void = cancelAnimationFrame,
) {
  let pending: number | null = null;
  let latest: T;
  let disposed = false;
  return {
    flush(value: T) {
      if (disposed) return;
      if (pending !== null) cancel(pending);
      pending = null;
      latest = value;
      notify(value);
    },
    push(value: T) {
      if (disposed) return;
      latest = value;
      if (pending !== null) return;
      pending = request(() => {
        pending = null;
        if (!disposed) notify(latest);
      });
    },
    dispose() {
      disposed = true;
      if (pending !== null) cancel(pending);
      pending = null;
    },
  };
}
