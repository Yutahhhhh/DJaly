import { useState, useSyncExternalStore } from "react";
import { open } from "@tauri-apps/plugin-dialog";
import { sampler } from "@/services/dj-engine/sampler";
export function SamplerPanel({ enabled, cueAvailable }: { enabled: boolean; cueAvailable: boolean }) {
  const bank = useSyncExternalStore(sampler.subscribe, sampler.getSnapshot);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<number | null>(null);
  const run = (task: () => Promise<unknown>) => { setError(null); void task().catch(e => setError(String(e))); };
  const load = (slot: number) => run(async () => {
    setBusy(slot);
    try { const path = await open({ multiple: false, filters: [{ name: "Audio", extensions: ["wav", "aiff", "aif", "flac", "mp3", "m4a", "ogg"] }] }); if (typeof path === "string") await sampler.load(slot, path); }
    finally { setBusy(null); }
  });
  return <section aria-label="サンプラー" className="dj-sampler">
    <div className="dj-sampler-toolbar"><strong>SAMPLER</strong><select aria-label="サンプラーバンク" value={bank.bank} disabled={!enabled} onChange={e => run(() => sampler.command("bank", {bank:Number(e.target.value)}))}>{[0,1,2,3].map(b => <option key={b} value={b}>BANK {b+1}</option>)}</select><label>音量 <input aria-label="サンプラー音量" type="range" min="0" max="1" step="0.01" value={bank.gain} disabled={!enabled} onChange={e => run(() => sampler.command("gain", {gain:Number(e.target.value)}))} /></label>
      <button disabled={!enabled || !cueAvailable} aria-pressed={bank.pfl} onClick={() => run(() => sampler.command("pfl", {enabled:!bank.pfl}))}>CUE</button>
      <button disabled={!enabled} onClick={() => run(() => sampler.command("stopAll"))}>全停止</button><span>SHIFT＋パッドで停止</span></div>
    {(error || bank.error) && <p role="alert">{error || bank.error}</p>}
    <div className="dj-sampler-slots">{bank.slots.map(s => <div key={s.slot} className="dj-sampler-slot">
      <button disabled={!enabled || !["ready", "playing"].includes(s.status)} aria-pressed={s.status === "playing"} onClick={e => run(() => sampler.trigger(s.slot, e.shiftKey))}>{s.slot + 1} · {s.status === "loading" ? "読み込み中…" : s.name || "空き"}</button>
      <div><button disabled={!enabled || busy !== null} onClick={() => load(s.slot)}>音源を選択</button><button disabled={!enabled || !s.path} onClick={() => run(() => sampler.trigger(s.slot, true))}>停止</button><button disabled={!enabled || !s.path} onClick={() => run(() => sampler.eject(s.slot))}>解除</button></div>
      {s.error && <small role="alert">{s.error}</small>}
    </div>)}</div>
  </section>;
}
