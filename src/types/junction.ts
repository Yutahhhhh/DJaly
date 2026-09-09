export interface JunctionSnapshot {
  active: boolean;
  sessionId: string | null;
  revision: number | string;
  localPeerId: string;
  hostPeerId: string;
  performerPeerId: string;
  nextPeerId?: string;
  epoch: string;
  handoffState: string;
  participants: { peerId: string; displayName: string; status?: string; approved?: boolean }[];
  readiness: { ready: boolean; reasons: string[] };
  program: { state: string; localMonitor?: "direct" | "program-delayed"; meter?: number; outputDevice?: string; recording?: boolean };
  connection: { state: string; detail?: string };
  invite?: string;
}
export type JunctionOp = 'snapshot' | 'create' | 'join' | 'leave' | 'end' | 'invite.rotate' | 'peer.approve' | 'handoff.request' | 'handoff.cancel' | 'handoff.accept' | 'recovery.resume' | 'program.configure' | 'program.record.start' | 'program.record.stop' | 'private.load' | 'private.play' | 'private.pause' | 'private.seek';
export interface JunctionLease { sessionId: string; epoch: string; actorPeerId: string }
