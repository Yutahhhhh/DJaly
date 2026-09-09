/** All deck surfaces share one browser frame. Input never waits for this queue. */
export function createPresentationScheduler(
  request: (callback: FrameRequestCallback) => number,
  cancel: (id: number) => void,
) {
  const callbacks = new Map<number, FrameRequestCallback>();
  let next = 0, frame: number | null = null;
  return {
    request(callback: FrameRequestCallback) {
      const id = ++next;
      callbacks.set(id, callback);
      if (frame === null) frame = request(time => {
        frame = null;
        const batch = [...callbacks];
        for (const [key, callback] of batch) {
          if (!callbacks.delete(key)) continue;
          callback(time);
        }
      });
      return id;
    },
    cancel(id: number) {
      callbacks.delete(id);
      if (!callbacks.size && frame !== null) { cancel(frame); frame = null; }
    },
  };
}
export const presentationScheduler = createPresentationScheduler(
  callback => requestAnimationFrame(callback), id => cancelAnimationFrame(id),
);
