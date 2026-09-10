import type { ExchangeGuidance, ExchangeActionId } from '@/services/junction/exchange-actions';
import { formatExpiry } from '@/services/junction/exchange-actions';
import type { ExchangeRoute } from '@/types/junction';

const ROUTE_LABEL: Record<ExchangeRoute, string> = {
  direct: '直接', relay: '中継（TURN）', mixed: '一部中継', unknown: '経路不明',
};

interface Props {
  title: string;
  peerHint?: string;
  attempt?: number;
  route?: ExchangeRoute;
  expiresAt?: number;
  nowMs: number;
  guidance: ExchangeGuidance;
  busy: boolean;
  error: string;
  message?: string;
  onAction: (id: ExchangeActionId) => void;
}

/** One per-DJ invitation / connection attempt. Error and next action shown together. */
export function InviteCard({ title, peerHint, attempt, route, expiresAt, nowMs, guidance, busy, error, message, onAction }: Props) {
  const expiry = formatExpiry(expiresAt, nowMs);
  return (
    <article className="junction-card" aria-busy={busy}>
      <header className="junction-card-head">
        <span className="junction-card-title" title={title}>{title}</span>
        {peerHint && <small className="junction-card-hint">{peerHint}</small>}
      </header>
      <p className="junction-card-headline"><span aria-hidden="true">{error || guidance.error ? "⚠ " : guidance.waiting ? "◌ " : guidance.headline.startsWith("接続済み") ? "✓ " : "→ "}</span>{guidance.headline}</p>
      {guidance.hint && <p className="junction-card-note">{guidance.hint}</p>}
      <p className="junction-card-meta">
        {typeof attempt === 'number' && attempt > 1 && <span>試行 {attempt} 回目</span>}

        {expiry && <span>{expiry}</span>}
      </p>
      {route && route !== 'unknown' && <details><summary>接続の詳細</summary><p>{ROUTE_LABEL[route]}接続</p></details>}
      {(error || guidance.error) && (
        <p className="junction-card-error" role="alert">
          {error || guidance.error}
        </p>
      )}
      {guidance.actions.length > 0 && (
        <div className="junction-card-actions">
          {guidance.actions.map((a) => (
            <button
              key={a.id}
              type="button"
              disabled={busy}
              className={`junction-btn junction-btn-${a.intent}`}
              onClick={() => onAction(a.id)}
            >
              {a.label}
            </button>
          ))}
        </div>
      )}
      {message && <p role="status" className="junction-card-note">{message}</p>}
      {(busy || guidance.waiting) && (
        <p className="junction-card-status" role="status">
          {busy ? '処理中…' : '状態は自動で更新されます'}
        </p>
      )}
    </article>
  );
}
