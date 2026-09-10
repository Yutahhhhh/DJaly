import type { AudioConfig, EngineSnapshot } from "../../types/dj-engine.ts";

export type OutputRouting = { masterChannels: number[]; pflChannels: number[] | null };
export const OUTPUT_ROUTING_KEY = "plumdeck.outputRouting";

type AudioClient = {
  getState(): { snapshot: EngineSnapshot | null };
  refreshSnapshot(): Promise<EngineSnapshot>;
  stop(): Promise<unknown>;
  start(output?: string, directory?: string): Promise<{ running: boolean; lastError?: string | null; detail?: string | null }>;
  connect(): Promise<unknown>;
};
const recovering = new WeakMap<AudioClient, Promise<AudioConfig>>();

/** A live process can have a permanently failed device. Reconnecting to that
 * process cannot reopen Core Audio. Recreate it once using the same selection. */
export function ensureAudioReady(client: AudioClient, output?: string, directory?: string): Promise<AudioConfig> {
  const pending = recovering.get(client);
  if (pending) return pending;
  const operation = (async () => {
    let current = await client.refreshSnapshot();
    if (current.audio.applied) return current.audio;
    if (current.recording?.active || current.recording?.stopping || Object.values(current.decks).some(deck => deck.status === "playing")) {
      throw new Error(current.audio.reason || "音声出力を再設定する前に再生・録音を停止してください。");
    }
    await client.stop();
    const started = await client.start(output, directory);
    if (!started.running) throw new Error(started.lastError || started.detail || "音声エンジンを起動できませんでした。");
    await client.connect();
    current = await client.refreshSnapshot();
    if (!current.audio.applied) throw new Error(`音声出力を開けません: ${current.audio.reason || "出力デバイスの初期化に失敗しました。"}`);
    return current.audio;
  })();
  recovering.set(client, operation);
  void operation.finally(() => recovering.delete(client)).catch(() => undefined);
  return operation;
}

export function parseOutputRouting(raw: string | null): { deviceId: string; routing: OutputRouting } | null {
  try {
    if (!raw) return null;
    const value = JSON.parse(raw);
    const pair = (v: unknown): v is number[] => Array.isArray(v) && v.length === 2 && v.every(n => Number.isInteger(n) && n >= 0) && v[1] === v[0] + 1;
    const route = value?.routing;
    if (typeof value?.deviceId !== "string" || !route || !pair(route.masterChannels) || (route.pflChannels !== null && !pair(route.pflChannels))) return null;
    if (route.pflChannels?.some((n: number) => route.masterChannels.includes(n))) return null;
    return value;
  } catch { return null; }
}
