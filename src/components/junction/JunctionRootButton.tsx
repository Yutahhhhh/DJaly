import type { JunctionSnapshot } from '@/types/junction';
import { describeExchangeState } from '@/services/junction/exchange-actions';

const CONNECTION_LABEL: Record<string, string> = {
  stable: '安定', connected: '接続済み', connecting: '接続中', unknown: '確認中', interrupted: '中断', reconnecting: '復旧待ち', error: '要確認', pending: 'ホストの操作待ち', closing: '終了中', disconnected: '未接続',
};

interface Props {
  snapshot: JunctionSnapshot | null;
  open: boolean;
  onToggle: () => void;
}

/** Compact root control: session name, role, host, current / next performer, status. */
export function JunctionRootButton({ snapshot, open, onToggle }: Props) {
  const active = Boolean(snapshot?.active);
  const host = active && snapshot?.hostPeerId === snapshot?.localPeerId;
  const nameOf = (id?: string) => {
    if (!id) return '—';
    const p = snapshot?.participants.find((x) => x.peerId === id);
    return (p?.displayName ?? '確認中') + (id === snapshot?.localPeerId ? '（自分）' : '');
  };
  const pending = active
    ? snapshot!.participants.filter((p) => p.exchange?.state === 'approval_pending' || ['failed','expired','needs_exchange','interrupted'].includes(p.exchange?.state ?? '')).length
    : 0;
  const status = active
    ? host && snapshot!.participants.length === 1 ? 'DJの参加待ち' : CONNECTION_LABEL[snapshot!.connection.state] ?? describeExchangeState(snapshot!.exchange?.state) ?? '確認中'
    : '停止中';

  return (
    <button
      id="junction-toggle"
      aria-controls="junction-panel"
      type="button"
      className="junction-root"
      aria-expanded={open}
      onClick={onToggle}
      title="Junction パネルを開閉"
    >
      <b>Junction</b>
      {active ? (
        <>
          <span className="junction-root-name" title={snapshot?.sessionName || undefined}>
            {snapshot?.sessionName?.trim() || '無名のセッション'}
          </span>
          <span>{host ? 'ホスト' : '参加者'}</span>
          <span className="junction-root-dim">ホスト：{nameOf(snapshot?.hostPeerId)}</span>
          <span>現在：{nameOf(snapshot?.performerPeerId)}</span>
          <span className="junction-root-dim">次：{snapshot?.nextPeerId ? nameOf(snapshot?.nextPeerId) : '未定'}</span>
          <span>接続：{status}</span>
          {pending > 0 && <span className="junction-root-badge" aria-label={`未対応 ${pending} 件`}>{pending}</span>}
        </>
      ) : (
        <span className="junction-root-dim">セッションなし</span>
      )}
    </button>
  );
}
