export type SampleAsset = { path: string; name: string };
export const SAMPLE_MIME = "application/x-plumdeck-sample";
const KEY = "plumdeck.sampler.library.v1";
const listeners = new Set<() => void>();
let assets: SampleAsset[] = [];
try {
  const stored: unknown = JSON.parse(localStorage.getItem(KEY) ?? "[]");
  if (Array.isArray(stored)) assets = stored.filter((v): v is SampleAsset => Boolean(v && typeof v.path === "string" && typeof v.name === "string"));
} catch { /* Start empty if storage is malformed. */ }
let drag: SampleAsset | null = null;
let claimed = false;
let clearTimer: ReturnType<typeof setTimeout> | undefined;
export const sampleDrag = {
  current: () => drag,
  start(asset: SampleAsset) { clearTimeout(clearTimer); drag = asset; claimed = false; },
  claim() { if (claimed) return false; claimed = true; return true; },
  end() { clearTimer = setTimeout(() => { drag = null; }, 500); },
};
function publish(next: SampleAsset[]) {
  localStorage.setItem(KEY, JSON.stringify(next));
  assets = next;
  listeners.forEach(notify => notify());
}
export const samplerLibrary = {
  subscribe(notify: () => void) { listeners.add(notify); return () => { listeners.delete(notify); }; },
  snapshot: () => assets,
  add(paths: string[]) {
    const accepted = paths.filter(path => /\.(wav|aiff?|flac|mp3|m4a|ogg|opus)$/i.test(path));
    if (!accepted.length) throw new Error("対応する音源ファイルをドロップしてください。");
    const next = new Map(assets.map(asset => [asset.path, asset]));
    accepted.forEach(path => next.set(path, { path, name: path.split(/[\\/]/).pop() || path }));
    publish([...next.values()]);
    return { accepted: accepted.length, skipped: paths.length - accepted.length };
  },
  remove(path: string) { publish(assets.filter(asset => asset.path !== path)); },
};
export function readSample(data: DataTransfer): SampleAsset | null {
  try {
    const value = JSON.parse(data.getData(SAMPLE_MIME));
    return value && typeof value.path === "string" && typeof value.name === "string" ? value : null;
  } catch { return null; }
}
