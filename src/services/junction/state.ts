import type { JunctionSnapshot, JunctionLease } from '../../types/junction.ts';
let snapshot: JunctionSnapshot | null = null;
const listeners = new Set<() => void>();
export const junctionState = {
  get: () => snapshot,
  active: () => Boolean(snapshot?.active && snapshot.sessionId),
  unavailable: () => { if (snapshot?.active) { snapshot = {...snapshot, connection: {state: "unknown", detail: "状態を再確認しています"}}; listeners.forEach(fn => fn()); } },
  subscribe: (fn: () => void) => { listeners.add(fn); return () => { listeners.delete(fn); }; },
  set: (value: JunctionSnapshot) => { snapshot = value; listeners.forEach(fn => fn()); },
};
export function captureJunctionLease(): JunctionLease | null {
  if (!snapshot?.active || !snapshot.sessionId) return null;
  return { sessionId: snapshot.sessionId, epoch: snapshot.epoch, actorPeerId: snapshot.localPeerId };
}
export const junctionLeaseKey = () => { const l = captureJunctionLease(); return l ? `${l.sessionId}:${l.epoch}:${l.actorPeerId}` : 'standalone'; };
