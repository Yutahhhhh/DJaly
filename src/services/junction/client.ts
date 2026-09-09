import { invoke, isTauri } from '@tauri-apps/api/core';
import { djEngineClient } from '../dj-engine/client';
import { junctionState } from './state';
import type { JunctionOp, JunctionSnapshot } from '../../types/junction';
import type { EngineReply } from '../../types/dj-engine';
export async function junctionCommand(op: JunctionOp, params: Record<string, unknown> = {}): Promise<unknown> {
  if (!isTauri()) throw new Error('Junctionはデスクトップアプリで利用できます。');
  if ((op === 'create' || op === 'join') && !(await djEngineClient.status()).running) {
    const started = await djEngineClient.start();
    if (!started.running) throw new Error(started.detail ?? '音声エンジンを起動できません');
  }
  if (!djEngineClient.getSessionId()) await djEngineClient.connect();
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
