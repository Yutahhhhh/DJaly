import { invoke, isTauri } from '@tauri-apps/api/core';
import { open as openFileDialog, save as saveFileDialog } from '@tauri-apps/plugin-dialog';
import { djEngineClient } from '../dj-engine/client';
import { junctionState } from './state';
import type {
  ExchangeInspection,
  JunctionOp,
  JunctionSnapshot,
  NetworkConfigureInput,
  NetworkSummary,
  NetworkTestResult,
} from '../../types/junction';
import type { EngineReply } from '../../types/dj-engine';

const DESKTOP_ONLY = 'Junctionはデスクトップアプリで利用できます。';
/** Native gateway packet budget. Keep in sync with junction_read/write_exchange_file. */
export const EXCHANGE_TEXT_MAX_BYTES = 128 * 1024;

let engineBoot: Promise<void> | undefined;
async function ensureEngine(): Promise<void> {
  if (!engineBoot) engineBoot = (async () => {
    if (!(await djEngineClient.status()).running) {
      const started = await djEngineClient.start();
      if (!started.running) throw new Error(started.detail ?? '音声エンジンを起動できません');
    }
    if (!djEngineClient.getSessionId()) await djEngineClient.connect();
  })().finally(() => { engineBoot = undefined; });
  return engineBoot;
}

export async function junctionCommand(op: JunctionOp, params: Record<string, unknown> = {}): Promise<unknown> {
  if (!isTauri()) throw new Error(DESKTOP_ONLY);
  await ensureEngine();
  const reply = await invoke<EngineReply>('junction_command', {sessionId: djEngineClient.getSessionId(), op, params});
  if (!reply.ok) throw new Error(reply.error?.message ?? 'Junctionへの接続に失敗しました');
  if (op === 'snapshot') {
    const s = reply.data as JunctionSnapshot;
    if (!s || typeof s.active !== 'boolean' || !Array.isArray(s.participants)) throw new Error('Junctionの状態を確認できません');
    junctionState.set(s);
  } else await junctionCommand('snapshot');
  return reply.data;
}

export async function checkJunctionActive(): Promise<boolean> {
  if (!isTauri()) return false;
  if (!(await djEngineClient.status()).running) return false;
  await junctionCommand('snapshot');
  return junctionState.active();
}

/**
 * Ops that require a running native engine but no active Junction session: manual packet
 * inspection and network-credential configuration. The native reply still
 * carries validation errors for malformed input.
 */
async function junctionStatelessCommand(op: JunctionOp, params: Record<string, unknown> = {}): Promise<unknown> {
  if (!isTauri()) throw new Error(DESKTOP_ONLY);
  await ensureEngine();
  const sessionId = djEngineClient.getSessionId();
  const reply = await invoke<EngineReply>('junction_command', {sessionId, op, params});
  if (!reply.ok) throw new Error(reply.error?.message ?? '操作を実行できませんでした');
  return reply.data;
}

/** Preview a pasted invite / answer / notice before acting on it. */
export async function junctionInspectExchange(text: string): Promise<ExchangeInspection> {
  const trimmed = text.trim();
  if (!trimmed) throw new Error('確認するテキストを貼り付けてください。');
  if (byteLength(trimmed) > EXCHANGE_TEXT_MAX_BYTES) throw new Error('テキストが大きすぎます。正しい交換用テキストか確認してください。');
  return await junctionStatelessCommand('exchange.inspect', {text: trimmed}) as ExchangeInspection;
}

export const junctionNetwork = {
  get: () => junctionStatelessCommand('network.get') as Promise<NetworkSummary>,
  configure: (input: NetworkConfigureInput) => junctionStatelessCommand('network.configure', input as unknown as Record<string, unknown>) as Promise<NetworkSummary>,
  clear: () => junctionStatelessCommand('network.clear') as Promise<NetworkSummary>,
  /** Real relay ICE gathering on the native side; not a mere parse. */
  test: (poll = false, cancel = false) => junctionStatelessCommand('network.test', {poll, cancel}) as Promise<NetworkTestResult>,
};

function byteLength(text: string): number {
  return new TextEncoder().encode(text).length;
}

// --- Explicit clipboard. Buttons only; never persisted. -----------------------
export async function copyExchangeText(text: string): Promise<void> {
  if (!text) throw new Error('コピーする内容がありません。');
  if (!navigator.clipboard?.writeText) throw new Error('この環境ではコピーを利用できません。手動で選択してコピーしてください。');
  await navigator.clipboard.writeText(text);
}
export async function readExchangeClipboard(): Promise<string> {
  if (!navigator.clipboard?.readText) throw new Error('この環境では貼り付けを利用できません。テキストを直接入力してください。');
  const text = await navigator.clipboard.readText();
  if (!text.trim()) throw new Error('クリップボードに文字がありません。');
  return text;
}

// --- File alternative to clipboard. Explicit dialog selection. ---------------
export async function readExchangeFile(): Promise<string | null> {
  if (!isTauri()) throw new Error(DESKTOP_ONLY);
  const path = await openFileDialog({multiple: false, filters: [{name: 'Junction 交換テキスト', extensions: ['txt', 'json', 'jct']}]});
  if (typeof path !== 'string') return null;
  const text = await invoke<string>('junction_read_exchange_file', {path});
  if (byteLength(text) > EXCHANGE_TEXT_MAX_BYTES) throw new Error('ファイルが大きすぎます。正しい交換用ファイルか確認してください。');
  return text;
}
export async function writeExchangeFile(text: string, defaultName = 'junction-exchange.txt'): Promise<boolean> {
  if (!isTauri()) throw new Error(DESKTOP_ONLY);
  if (!text) throw new Error('保存する内容がありません。');
  const path = await saveFileDialog({defaultPath: defaultName, filters: [{name: 'Junction 交換テキスト', extensions: ['txt']}]});
  if (!path) return false;
  await invoke('junction_write_exchange_file', {path, text});
  return true;
}
