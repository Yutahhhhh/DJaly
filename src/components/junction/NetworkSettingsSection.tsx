import { useEffect, useState } from 'react';
import { isTauri } from '@tauri-apps/api/core';
import { junctionNetwork } from '@/services/junction/client';
import type { NetworkConfigureInput, NetworkSummary, NetworkTestResult, TurnMode } from '@/types/junction';

type TurnChoice = 'none' | TurnMode;
const DAY_MS = 24 * 60 * 60 * 1000;

const TEST_LABEL: Record<NetworkTestResult['state'], string> = {
  checking: '確認中…',
  success: '中継サーバーに接続先を取得できました',
  failure: '中継サーバーに接続先を取得できませんでした',
  timeout: '応答がありませんでした（タイムアウト）',
};

/**
 * Network credentials are configured here, separately from the session. STUN is
 * an advanced edit; TURN takes either a REST shared secret or short-lived
 * temporary credentials. Nothing here needs a signaling server URL.
 */
export function NetworkSettingsSection() {
  const [expanded, setExpanded] = useState(false);
  const [summary, setSummary] = useState<NetworkSummary | null>(null);
  const [stunText, setStunText] = useState('');
  const [turnChoice, setTurnChoice] = useState<TurnChoice>('none');
  const [turnUrls, setTurnUrls] = useState('');
  const [secret, setSecret] = useState('');
  const [username, setUsername] = useState('');
  const [credential, setCredential] = useState('');
  const [expiresAt, setExpiresAt] = useState('');
  const [save, setSave] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [test, setTest] = useState<NetworkTestResult | null>(null);

  const load = () => {
    if (!isTauri()) return;
    void junctionNetwork
      .get()
      .then((s) => {
        setSummary(s);
        setStunText(s.stunUrls.join('\n'));
        if (s.turn) {
          setTurnChoice(s.turn.mode);
          setTurnUrls(s.turn.urls.join('\n'));
          setUsername(s.turn.username ?? '');
        }
      })
      .catch((e) => setError(e instanceof Error ? e.message : String(e)));
  };
  useEffect(() => { if (expanded) load(); }, [expanded]);

  const lines = (text: string) => text.split(/\r?\n/).map((l) => l.trim()).filter(Boolean);

  const buildInput = (): NetworkConfigureInput => {
    const base: NetworkConfigureInput = { stunUrls: lines(stunText), save };
    if (turnChoice === 'none') return { ...base, turn: {} };
    if (turnChoice === 'rest') {
      return { ...base, turn: { mode: 'rest', urls: lines(turnUrls), secret: secret || undefined } };
    }
    const expMs = expiresAt ? Date.parse(expiresAt) : NaN;
    if (Number.isFinite(expMs) && expMs - Date.now() > DAY_MS) {
      throw new Error('一時クレデンシャルの有効期限は24時間以内にしてください。');
    }
    return {
      ...base,
      turn: {
        mode: 'temporary',
        urls: lines(turnUrls),
        username: username || undefined,
        credential: credential || undefined,
        expiresAt: Number.isFinite(expMs) ? expMs : undefined,
      },
    };
  };

  const run = async (fn: () => Promise<NetworkSummary>) => {
    setBusy(true);
    setError('');
    try {
      const next = await fn();
      setSummary(next);
      setStunText(next.stunUrls.join("\n"));
      setTurnChoice(next.turn?.mode ?? "none");
      setTurnUrls(next.turn?.urls.join("\n") ?? "");
      if (next.errors?.length) setError(next.errors.join(' / '));
      setSecret('');
      setCredential('');
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const apply = () => {
    let input: NetworkConfigureInput;
    try {
      input = buildInput();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      return;
    }
    void run(() => junctionNetwork.configure(input));
  };

  const runTest = () => {
    setBusy(true);
    setError('');
    setTest({ state: 'checking' });
    void junctionNetwork
      .test()
      .then(async (result) => {
        setTest(result);
        while (result.state === 'checking') {
          await new Promise((resolve) => setTimeout(resolve, 500));
          result = await junctionNetwork.test(true);
          setTest(result);
        }
      })
      .catch((e) => {
        setTest(null);
        setError(e instanceof Error ? e.message : String(e));
      })
      .finally(() => setBusy(false));
  };

  return (
    <details id="junction-network-settings" className="junction-section" onToggle={(event) => setExpanded(event.currentTarget.open)}>
      <summary>直接つながらないときの中継設定</summary>
      {expanded && <div>
      <h3>ネットワーク設定（セッションとは別）</h3>
      <p className="junction-card-note">
        通常は設定不要です。直接つながらないときは、ホストが用意した中継（TURN）を利用できます。回線によっては接続できない場合もあります。設定は新しく作る招待から反映されます。
      </p>

      <label>
        中継（TURN）の指定方法
        <select value={turnChoice} onChange={(e) => setTurnChoice(e.target.value as TurnChoice)} disabled={busy}>
          <option value="none">使わない</option>
          <option value="rest">共有シークレット（REST）</option>
          <option value="temporary">一時クレデンシャル（期限付き）</option>
        </select>
      </label>

      {turnChoice !== 'none' && (
        <>
          <label>
            TURN サーバー（1行に1つ）
            <textarea
              value={turnUrls}
              onChange={(e) => setTurnUrls(e.target.value)}
              rows={2}
              placeholder={'turn:example.net:3478\nturns:example.net:5349'}
              disabled={busy}
            />
          </label>
          {turnChoice === 'rest' ? (
            <label>
              共有シークレット（招待・返答には含めません）
              <input
                type="password"
                value={secret}
                onChange={(e) => setSecret(e.target.value)}
                autoComplete="off"
                disabled={busy}
              />
            </label>
          ) : (
            <>
              <label>
                ユーザー名
                <input value={username} onChange={(e) => setUsername(e.target.value)} autoComplete="off" disabled={busy} />
              </label>
              <label>
                クレデンシャル
                <input
                  type="password"
                  value={credential}
                  onChange={(e) => setCredential(e.target.value)}
                  autoComplete="off"
                  disabled={busy}
                />
              </label>
              <label>
                有効期限（24時間以内）
                <input type="datetime-local" value={expiresAt} onChange={(e) => setExpiresAt(e.target.value)} disabled={busy} />
              </label>
            </>
          )}
        </>
      )}

      <label className="junction-check">
        <input type="checkbox" checked={save} onChange={(e) => setSave(e.target.checked)} disabled={busy} />
        OSの保護機能を使ってこの端末に保存する（オフだとアプリ内メモリのみ）
      </label>

      <div className="junction-card-actions">
        <button type="button" className="junction-btn junction-btn-primary" disabled={busy} onClick={apply}>
          設定を適用
        </button>
        <button type="button" className="junction-btn junction-btn-default" disabled={busy} onClick={() => void run(() => junctionNetwork.clear())}>
          設定を解除
        </button>
        <button type="button" className="junction-btn junction-btn-default" disabled={busy} onClick={runTest}>
          中継サーバーへ接続テスト
        </button>
      </div>

      {test?.state === 'checking' && <button type="button" className="junction-btn junction-btn-default" onClick={() => void junctionNetwork.test(false, true).then(setTest).catch((e) => setError(String(e)))}>接続テストを中止</button>}
      {test && (
        <p className="junction-card-status" role="status">
          {TEST_LABEL[test.state]}
          {test.detail ? ` — ${test.detail}` : ''}
        </p>
      )}
      {error && (
        <p className="junction-card-error" role="alert">
          {error}
        </p>
      )}

      <details>
        <summary>詳細設定：STUN サーバー</summary>
        <p className="junction-card-note">
          既定の公開STUNのままで構いません。隔離環境で試すときは空にできます。
        </p>
        <label>
          STUN サーバー（1行に1つ）
          <textarea value={stunText} onChange={(e) => setStunText(e.target.value)} rows={3} disabled={busy} />
        </label>
      </details>

      {summary && (
        <p className="junction-card-note">
          現在：STUN {summary.stunUrls.length} 件 ／ 中継{' '}
          {summary.turn
            ? `${summary.turn.mode === 'rest' ? '共有シークレット' : '一時クレデンシャル'}（${summary.turn.urls.length} 件${
                summary.turn.hasSecret ? '・シークレット保持' : ''
              }${summary.turn.expiresAt ? `・期限 ${new Date(summary.turn.expiresAt).toLocaleString()}` : ''}）`
            : 'なし'}
          ／ 保存 {summary.saved ? 'あり（この端末）' : 'なし'}
        </p>
      )}
      </div>}
    </details>
  );
}
