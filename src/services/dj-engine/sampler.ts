import { djEngineClient } from "./client";
export type SamplerSlot = { slot: number; path: string; name: string; status: "empty" | "loading" | "ready" | "playing" | "error"; error: string; durationMs: number; revision: number };
export type SamplerState = { slots: SamplerSlot[]; bank: number; gain: number; pfl: boolean; error?: string };
const EMPTY: SamplerState = { bank: 0, slots: Array.from({ length: 16 }, (_, slot) => ({ slot, path: "", name: "", status: "empty", error: "", durationMs: 0, revision: 0 })), gain: 0.7, pfl: false };
let state = EMPTY, session: string | null = null, polling = false;
const listeners = new Set<() => void>();
const publish = (next: SamplerState) => { state = next; for (const notify of listeners) notify(); };
const valid = (data: unknown): data is SamplerState => {
  const s = data as SamplerState;
  return Boolean(s && Array.isArray(s.slots) && s.slots.length === 16 && s.slots.every((v, i) => v.slot === i && typeof v.path === "string" && Number.isSafeInteger(v.revision)) && Number.isFinite(s.gain) && typeof s.pfl === "boolean");
};
function saved(): string[] {
  try { const paths = JSON.parse(localStorage.getItem("djaly.sampler.paths") ?? "[]"); return Array.from({length:64}, (_, i) => typeof paths[i] === "string" ? paths[i] : ""); } catch { return []; }
}
export const sampler = {
  getSnapshot: () => state,
  subscribe: (notify: () => void) => { listeners.add(notify); return () => { listeners.delete(notify); }; },
  async command(op: string, params: Record<string, unknown> = {}) {
    const currentSession = djEngineClient.getSessionId();
    const reply = await djEngineClient.send(`sampler.${op}`, params);
    if (currentSession === djEngineClient.getSessionId() && valid(reply)) publish(reply);
    return reply;
  },
  async load(slot: number, path: string) {
    const bank = state.bank;
    await this.command("load", { slot, path, bank });
    const paths = saved(); paths[bank * 16 + slot] = path; localStorage.setItem("djaly.sampler.paths", JSON.stringify(paths));
  },
  async eject(slot: number) {
    const bank = state.bank;
    await this.command("eject", { slot, bank });
    const paths = saved(); paths[bank * 16 + slot] = ""; localStorage.setItem("djaly.sampler.paths", JSON.stringify(paths));
  },
  async trigger(slot: number, stop = false) {
    const sample = state.slots[slot];
    if (!sample) throw new Error("サンプラースロットが不正です");
    await this.command(stop ? "stop" : "play", { slot, bank: state.bank, revision: sample.revision });
  },
  async poll() {
    if (polling) return;
    const nextSession = djEngineClient.getSessionId();
    if (!nextSession) { if (session) { session = null; publish(EMPTY); } return; }
    if (!djEngineClient.getState().snapshot?.engine.capabilities.includes("sampler")) return;
    polling = true;
    try {
      if (session !== nextSession) {
        session = nextSession; publish(EMPTY);
        const paths = saved();
        for (let slot = 0; slot < paths.length; slot++) {
          if (djEngineClient.getSessionId() !== nextSession) return;
          if (paths[slot]) await this.command("load", { slot: slot % 16, bank: Math.floor(slot / 16), path: paths[slot] }).catch(e => publish({ ...state, error: String(e) }));
        }
      }
      await this.command("state");
    } catch (e) { if (djEngineClient.getSessionId() === nextSession) publish({ ...state, error: String(e) }); }
    finally { polling = false; }
  },
};
