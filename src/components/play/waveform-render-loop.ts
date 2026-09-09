/** Coalesce resize/telemetry/interaction into one paint per display frame. */
export function createWaveformRenderLoop(
  draw: () => void,
  continuous: () => boolean,
  request: (callback: FrameRequestCallback) => number = requestAnimationFrame,
  cancel: (id: number) => void = cancelAnimationFrame,
) {
  let pending: number | null = null;
  let disposed = false;
  const invalidate = () => {
    if (!disposed && pending === null) pending = request(frame);
  };
  const frame = () => {
    pending = null;
    if (disposed) return;
    draw();
    if (continuous()) invalidate();
  };
  return {
    invalidate,
    dispose() { disposed = true; if (pending !== null) cancel(pending); pending = null; },
  };
}
