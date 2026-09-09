import { useState, useSyncExternalStore } from "react";
import { open } from "@tauri-apps/plugin-dialog";
import { sampler } from "@/services/dj-engine/sampler";

/** Eight hardware-aligned pads, with sample management kept inside the deck. */
export function SamplerPads({ offset, enabled, cueAvailable }: { offset: number; enabled: boolean; cueAvailable: boolean }) {
  const state = useSyncExternalStore(sampler.subscribe, sampler.getSnapshot);
  const [selected, setSelected] = useState(offset);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const run = (task: () => Promise<unknown>) => { setError(""); void task().catch(e => setError(String(e))); };
  const load = (slot: number) => run(async () => {
    const bank = state.bank;
    setBusy(true);
    try {
      const path = await open({ multiple: false, filters: [{ name: "Audio", extensions: ["wav", "aiff", "aif", "flac", "mp3", "m4a", "ogg"] }] });
      if (typeof path !== "string") return;
      if (sampler.getSnapshot().bank !== bank) throw new Error("バンクが変更されました。音源を選び直してください。");
      await sampler.load(slot, path);
    } finally { setBusy(false); }
  });
  const sample = state.slots[selected];
  return <>
    <div className="dj-pad-grid dj-sampler-pads" aria-label="SAMPLERパッド">
      {state.slots.slice(offset, offset + 8).map(s => <button key={s.slot} type="button"
        className={`dj-performance-pad${s.status === "playing" ? " is-on" : ""}`}
        disabled={!enabled || busy || s.status === "loading"} aria-pressed={s.status === "playing"}
        title={`${s.name || "クリックして音源を選択"} · SHIFTで停止`}
        onClick={e => { setSelected(s.slot); if (s.path) run(() => sampler.trigger(s.slot, e.shiftKey)); else if (!e.shiftKey) load(s.slot); }}>
        <b>{s.slot + 1} · {s.status === "loading" ? "読込中" : s.name || "＋ 音源"}</b>
      </button>)}
    </div>
    <div className="dj-sampler-pad-tools">
      <select aria-label="編集するサンプラーPAD" value={selected} onChange={e => setSelected(Number(e.target.value))}>
        {state.slots.slice(offset, offset + 8).map(s => <option key={s.slot} value={s.slot}>PAD {s.slot + 1}</option>)}
      </select>
      <button disabled={!enabled || busy} onClick={() => load(selected)}>音源</button>
      <button disabled={!enabled || !sample?.path} onClick={() => run(() => sampler.trigger(selected, true))}>停止</button>
      <button disabled={!enabled || busy || !sample?.path} onClick={() => run(() => sampler.eject(selected))}>解除</button>
      <button disabled={!enabled} onClick={() => run(() => sampler.command("stopAll"))}>全停止</button>
      <button disabled={!enabled || !cueAvailable} aria-pressed={state.pfl} onClick={() => run(() => sampler.command("pfl", { enabled: !state.pfl }))}>CUE</button>
      <label>音量 <input aria-label="サンプラー音量" type="range" min="0" max="1" step="0.01" value={state.gain} disabled={!enabled} onChange={e => run(() => sampler.command("gain", { gain: Number(e.target.value) }))} /></label>
    </div>
    {(error || sample?.error || state.error) && <small role="alert">{error || sample?.error || state.error}</small>}
  </>;
}
