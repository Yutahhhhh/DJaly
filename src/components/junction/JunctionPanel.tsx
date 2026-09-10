import { useEffect, useMemo, useRef, useState } from 'react';
import { open as openAudioDialog, save as saveDialog } from '@tauri-apps/plugin-dialog';
import type { AudioDevice } from '@/types/dj-engine';
import type { ExchangeInspection, JunctionOp, JunctionSnapshot } from '@/types/junction';
import { useJunction } from '@/hooks/useJunction';
import { djEngineClient } from '@/services/dj-engine/client';
import {
  copyExchangeText,
  junctionCommand,
  junctionNetwork,
  junctionInspectExchange,
  readExchangeClipboard,
  readExchangeFile,
  writeExchangeFile,
} from '@/services/junction/client';
import {
  deriveGuestGuidance,
  deriveHostCardGuidance,
  describeExchangeState,
  type ExchangeActionId,
} from '@/services/junction/exchange-actions';
import { InviteCard } from './InviteCard';
import { NetworkSettingsSection } from './NetworkSettingsSection';
import './junction.css';

const STAGES: Record<string, string> = {
  playing: 'プレイ中', switching: '配信への反映待ち', recovery: '接続の復旧待ち',
  IDLE: '待機中', PREPARING: '準備中', READY: '引き継ぎ可能', FENCE: '引き継ぎを確認中',
  COMMITTED: '配信への反映待ち', COMPLETE: '配信へ反映済み',
  idle: '待機中', preparing: '準備中', ready: '引き継ぎ可能', fenced: '引き継ぎを確認中',
  committed: '配信への反映待ち', complete: '配信へ反映済み',
};

interface CardState { busy: boolean; error: string; message?: string }
type CardMap = Record<string, CardState>;

interface Props {
  open: boolean;
  onClose: () => void;
  incomingInvite: string | null;
  onConsumeIncoming: () => void;
  notice?: string;
  onDismissNotice?: () => void;
}

export function JunctionPanel({ open, onClose, incomingInvite, onConsumeIncoming, notice, onDismissNotice }: Props) {
  const s = useJunction();
  const panelRef = useRef<HTMLDivElement | null>(null);
  const headingRef = useRef<HTMLHeadingElement | null>(null);

  const active = Boolean(s?.active);
  const host = active && s?.hostPeerId === s?.localPeerId;
  const isServerMode = s?.exchange?.mode === 'server' || Boolean(s?.invite && !s?.exchange);

  const [name, setName] = useState(() => localStorage.getItem('plumdeck.junction.name') ?? '');
  const [sessionName, setSessionName] = useState('');
  const [joinText, setJoinText] = useState('');
  const [importText, setImportText] = useState('');
  const [inspecting, setInspecting] = useState(false);
  const [preview, setPreview] = useState<ExchangeInspection | null>(null);
  const [programDevice, setProgramDevice] = useState('');
  const [adoptCurrent, setAdoptCurrent] = useState(false);
  const [devices, setDevices] = useState<AudioDevice[]>([]);
  const [privatePath, setPrivatePath] = useState('');
  const [position, setPosition] = useState(0);
  const [entryBusy, setEntryBusy] = useState(false);
  const [entryError, setEntryError] = useState('');
  const [cards, setCards] = useState<CardMap>({});
  const [nowMs, setNowMs] = useState(() => Date.now());

  // Keep a coarse clock for expiry text without faking progress.
  useEffect(() => {
    if (!open) return;
    const t = setInterval(() => setNowMs(Date.now()), 5000);
    return () => clearInterval(t);
  }, [open]);

  useEffect(() => {
    if (open) {
      void junctionNetwork.get().then(() => djEngineClient.listAudioDevices())
        .then((data) => setDevices((data as { devices?: AudioDevice[] }).devices ?? []))
        .catch(() => {});
    }
  }, [open, active]);

  // Move focus into the panel on open; do not trap (nonmodal).
  useEffect(() => {
    if (open) headingRef.current?.focus();
  }, [open]);

  // A legacy pending invite handed in from the host process.
  useEffect(() => {
    if (incomingInvite && !active) {
      setJoinText(incomingInvite);
      onConsumeIncoming();
    }
  }, [incomingInvite, active, onConsumeIncoming]);

  const setCard = (key: string, patch: Partial<CardState>) =>
    setCards((prev) => {
      const current: CardState = prev[key] ?? { busy: false, error: '' };
      return { ...prev, [key]: { ...current, ...patch } };
    });

  const cardOf = (key: string): CardState => cards[key] ?? { busy: false, error: '' };

  const runEntry = async (op: JunctionOp, params: Record<string, unknown>) => {
    setEntryBusy(true);
    setEntryError('');
    try {
      localStorage.setItem('plumdeck.junction.name', name);
      await junctionCommand(op, params);
      setJoinText('');
      setPreview(null);
    } catch (e) {
      setEntryError(e instanceof Error ? e.message : String(e));
    } finally {
      setEntryBusy(false);
    }
  };

  const runInspect = async () => {
    setInspecting(true);
    setEntryError('');
    setPreview(null);
    try {
      setPreview(await junctionInspectExchange(joinText));
    } catch (e) {
      setEntryError(e instanceof Error ? e.message : String(e));
    } finally {
      setInspecting(false);
    }
  };

  const runCard = async (key: string, fn: () => Promise<unknown>) => {
    setCard(key, { busy: true, error: '', message: '' });
    try {
      await fn();
    } catch (e) {
      setCard(key, { error: e instanceof Error ? e.message : String(e) });
    } finally {
      setCard(key, { busy: false });
    }
  };

  const selfExchange = useMemo(
    () => s?.participants.find((p) => p.peerId === s?.hostPeerId)?.exchange,
    [s],
  );

  const handleCardAction = (peerId: string, id: ExchangeActionId) => {
    const key = peerId;
    const p = s?.participants.find((x) => x.peerId === peerId);
    const x = peerId === 'self' ? selfExchange : p?.exchange;
    const inviteText = x?.inviteText ?? s?.exchange?.responseText ?? s?.invite ?? '';
    const noticeText = x?.noticeText ?? '';
    switch (id) {
      case 'open_relay': { const node = document.getElementById('junction-network-settings') as HTMLDetailsElement | null; if (node) { node.open = true; node.scrollIntoView({block: 'start', behavior: 'smooth'}); node.querySelector('summary')?.focus(); } return; }
      case 'copy_invite':
      case 'copy_answer':
        return void runCard(key, async () => { await copyExchangeText(inviteText); setCard(key, {message: id === 'copy_invite' ? '招待をコピーしました。この招待を参加するDJへ送ってください。' : '返答をコピーしました。ホストへ送り、接続を待ってください。'}); });
      case 'save_invite_file':
      case 'save_answer_file':
        return void runCard(key, () => writeExchangeFile(inviteText, 'junction-exchange.txt'));
      case 'copy_notice':
        return void runCard(key, () => copyExchangeText(noticeText));
      case 'save_notice_file':
        return void runCard(key, () => writeExchangeFile(noticeText, 'junction-notice.txt'));
      case 'paste_answer':
      case 'paste_invite':
        return void runCard(key, async () => {
          const text = await readExchangeClipboard();
          await junctionCommand('exchange.import', { text });
        });
      case 'import_answer_file':
      case 'import_invite_file':
        return void runCard(key, async () => {
          const text = await readExchangeFile();
          if (text != null) await junctionCommand('exchange.import', { text });
        });
      case 'approve':
        return void runCard(key, () => junctionCommand('peer.approve', { peerId, accept: true }));
      case 'reject':
        return void runCard(key, () => junctionCommand('peer.approve', { peerId, accept: false }));
      case 'retry':
        return void runCard(key, () => junctionCommand('peer.retry', { peerId }));
      case 'reexchange':
        return void runCard(key, () => junctionCommand('invite.create', { peerId }));
      case 'cancel':
      case 'dismiss':
        return void runCard(key, () => junctionCommand('invite.cancel', { peerId }));
      default:
        return undefined;
    }
  };

  const onPanelKeyDown = (event: React.KeyboardEvent) => {
    event.stopPropagation();
    // Escape closes the panel only; it must not bubble to deck shortcuts.
    if (event.key === 'Escape') {
      event.stopPropagation();
      onClose();
    }
  };

  const outputOptions = devices.filter((d) => d.outputChannels >= 2);
  const deviceValue = (id: string) => (/^coreaudio:\d+$/.test(id) ? id.slice(10) : id);

  return (
    <div
      id="junction-panel"
      ref={panelRef}
      className={`junction-panel${open ? ' junction-panel-open' : ''}`}
      role="complementary"
      aria-label="Junction セッション"
      aria-hidden={!open}
      inert={!open}
      onKeyDown={onPanelKeyDown}
      onKeyUp={(event) => event.stopPropagation()}
    >
      <div className="junction-panel-head">
        <h2 tabIndex={-1} ref={headingRef}>Junction</h2>
        <button type="button" className="junction-btn junction-btn-default" onClick={onClose} aria-label="パネルを閉じる">
          閉じる
        </button>
      </div>

      <div className="junction-panel-body">
        {notice && (
          <p className="junction-card-error" role="alert">
            {notice}
            {onDismissNotice && (
              <button type="button" className="junction-btn junction-btn-default" onClick={onDismissNotice}>
                閉じる
              </button>
            )}
          </p>
        )}
        {active && (
          <div className="junction-statusbar" aria-live="polite">
            <span title={s?.sessionName || undefined}>{s?.sessionName?.trim() || '無名のセッション'}</span>
            <span>{host ? 'ホスト' : '参加者'}</span>
            <span>現在：{peerName(s, s?.performerPeerId)}</span>
            <span>次：{s?.nextPeerId ? peerName(s, s?.nextPeerId) : '未定'}</span>
            <span>{STAGES[s!.handoffState] ?? '状態確認中'}</span>
            <span>接続：{describeExchangeState(s?.exchange?.state)}</span>
          </div>
        )}

        {!active ? (
          <EntrySection
            name={name}
            setName={setName}
            sessionName={sessionName}
            setSessionName={setSessionName}
            joinText={joinText}
            setJoinText={(v) => { setJoinText(v); setPreview(null); }}
            outputOptions={outputOptions}
            deviceValue={deviceValue}
            programDevice={programDevice}
            setProgramDevice={setProgramDevice}
            adoptCurrent={adoptCurrent}
            setAdoptCurrent={setAdoptCurrent}
            busy={entryBusy}
            inspecting={inspecting}
            error={entryError}
            preview={preview}
            onInspect={() => void runInspect()}
            onCreate={() =>
              void runEntry('create', {
                displayName: name,
                sessionName,
                programDevice,
                adoptCurrent,
                exchangeMode: 'manual',
              })
            }
            onFileError={(message) => setEntryError(message)}
            onJoin={() => void runEntry('join', { displayName: name, text: joinText })}
          />
        ) : (
          <>
            {host ? (
              <section className="junction-section">
                <h3>招待するDJ</h3>
                <p className="junction-card-note">
                  DJごとに1枚のカードを作り、招待を渡します。取り込んだ返答を確認・承認してから接続します。
                </p>
                <button
                  type="button"
                  className="junction-btn junction-btn-primary"
                  disabled={cardOf('new').busy}
                  onClick={() => void runCard('new', () => junctionCommand('invite.create', {}))}
                >
                  新しいDJの招待を作成
                </button>
                {cardOf('new').error && (
                  <p className="junction-card-error" role="alert">{cardOf('new').error}</p>
                )}
                {guestParticipants(s).map((p) => {
                  const g = deriveHostCardGuidance(p);
                  const c = cardOf(p.peerId);
                  return (
                    <InviteCard
                      key={p.peerId}
                      title={p.displayName || '名前未取得のDJ'}
                      peerHint={`${p.peerId.slice(0, 8)}${p.approved === false ? ' · 未承認' : ''}`}
                      attempt={p.exchange?.attempt}
                      route={p.exchange?.route}
                      expiresAt={p.exchange?.state === 'connected' ? undefined : p.exchange?.expiresAt}
                      nowMs={nowMs}
                      guidance={g}
                      busy={c.busy}
                      error={c.error}
                      message={c.message}
                      onAction={(id) => handleCardAction(p.peerId, id)}
                    />
                  );
                })}
                {guestParticipants(s).length === 0 && (
                  <p className="junction-card-note">まだ招待カードはありません。</p>
                )}
              </section>
            ) : (
              <section className="junction-section">
                <h3>ホストとの接続</h3>
                <InviteCard
                  title="あなたの参加"
                  peerHint={selfExchange?.inviteId ? `招待 ${selfExchange.inviteId.slice(0, 8)}` : undefined}
                  attempt={selfExchange?.attempt}
                  route={selfExchange?.route}
                  expiresAt={s?.exchange?.state === 'connected' ? undefined : selfExchange?.expiresAt ?? s?.exchange?.expiresAt}
                  nowMs={nowMs}
                  guidance={deriveGuestGuidance(s as JunctionSnapshot)}
                  busy={cardOf('self').busy}
                  error={cardOf('self').error}
                  message={cardOf('self').message}
                  onAction={(id) => handleCardAction('self', id)}
                />
              </section>
            )}

            {!isServerMode && <section className="junction-section">
              <details>
                <summary>{host ? 'DJから届いた返答を取り込む' : 'ホストから届いた新しい招待・通知を取り込む'}</summary>
                <label>受け取ったテキスト<textarea value={importText} onChange={(e) => setImportText(e.target.value)} maxLength={131072} rows={3} /></label>
                <button type="button" className="junction-btn junction-btn-primary" disabled={!importText.trim() || cardOf('import').busy} onClick={() => void runCard('import', async () => { await junctionCommand('exchange.import', {text: importText}); setImportText(''); })}>取り込む</button>
                {cardOf('import').error && <p role="alert" className="junction-card-error">{cardOf('import').error}</p>}
              </details>
            </section>}
            <section className="junction-section">
              <h3>参加者と引き継ぎ</h3>
              <p aria-live="polite" className="junction-card-note">
                {STAGES[s!.handoffState] ?? '引き継ぎ状態を確認中'}
                {s?.readiness.reasons?.length ? ` · ${s.readiness.reasons.join('・')}` : ''}
              </p>
              {s!.participants.map((p) => (
                <div className="junction-peer" key={p.peerId}>
                  <span>
                    {peerName(s, p.peerId)}{' '}
                    <small>
                      {p.peerId.slice(0, 8)}
                      {p.peerId === s?.hostPeerId ? ' · ホスト' : ''}
                      {p.peerId === s?.performerPeerId ? ' · プレイ中' : ''}
                      {p.peerId === s?.nextPeerId ? ' · 次のDJ' : ''}
                      {p.exchange ? ` · ${describeExchangeState(p.exchange.state)}` : ''}
                    </small>
                  </span>
                  {host && p.approved !== false && p.peerId !== s?.performerPeerId && (
                    <button
                      type="button"
                      className="junction-btn junction-btn-default"
                      disabled={cardOf(`ho:${p.peerId}`).busy}
                      onClick={() => void runCard(`ho:${p.peerId}`, () => junctionCommand('handoff.request', { targetPeerId: p.peerId }))}
                    >
                      次DJに指定
                    </button>
                  )}
                </div>
              ))}
              {djEngineClient.getState().snapshot?.audio.microphone?.enabled && (
                <button
                  type="button"
                  className="junction-btn junction-btn-default"
                  disabled={cardOf('mic').busy}
                  onClick={() =>
                    void runCard('mic', async () => {
                      await djEngineClient.setMicrophone({ enabled: false });
                      await junctionCommand('snapshot');
                    })
                  }
                >
                  マイクを閉じて引き継ぐ
                </button>
              )}
              <div className="junction-card-actions">
                <button type="button" className="junction-btn junction-btn-default" disabled={cardOf('hf').busy}
                  onClick={() => void runCard('hf', () => junctionCommand('handoff.request', { targetPeerId: s?.localPeerId }))}>
                  次にプレイする
                </button>
                <button type="button" className="junction-btn junction-btn-primary"
                  disabled={cardOf('hf').busy || !s?.readiness.ready || s?.nextPeerId !== s?.localPeerId}
                  onClick={() => void runCard('hf', () => junctionCommand('handoff.accept'))}>
                  操作を引き継ぐ
                </button>
                <button type="button" className="junction-btn junction-btn-default" disabled={cardOf('hf').busy || !host}
                  onClick={() => void runCard('hf', () => junctionCommand('handoff.cancel'))}>
                  引き継ぎを取消
                </button>
              </div>
              {cardOf('hf').error && <p className="junction-card-error" role="alert">{cardOf('hf').error}</p>}
              {host && s?.handoffState === 'recovery' && (
                <button type="button" className="junction-btn junction-btn-primary" disabled={cardOf('rec').busy}
                  onClick={() => void runCard('rec', () => junctionCommand('recovery.resume'))}>
                  ホストの手元の演奏で配信を再開
                </button>
              )}
            </section>

            {host && (
              <section className="junction-section">
                <h3>配信先</h3>
                <p className="junction-card-note">
                  配信出力：{s?.program.state === 'running' ? '稼働中' : s?.program.state === 'error' ? '出力エラー' : '準備中'}
                </p>
                {s?.program.localMonitor === 'program-delayed' && (
                  <p className="junction-card-note">配信先とローカル出力先が同じため、メイン音は配信出力から再生します（遅延あり）。</p>
                )}
                {typeof s?.program.meter === 'number' && (
                  <meter aria-label="Program メーター" min={0} max={1} value={s.program.meter} />
                )}
                <label>
                  出力デバイス
                  <select value={programDevice} onChange={(e) => setProgramDevice(e.target.value)}>
                    <option value="">配信先を選択</option>
                    {outputOptions.map((d) => (
                      <option key={d.id} value={deviceValue(d.id)}>{d.name}</option>
                    ))}
                  </select>
                </label>
                <div className="junction-card-actions">
                  <button type="button" className="junction-btn junction-btn-default" disabled={cardOf('prog').busy}
                    onClick={() => void runCard('prog', () => junctionCommand('program.configure', { programDevice }))}>
                    配信先を適用
                  </button>
                  <button type="button" className="junction-btn junction-btn-default" disabled={cardOf('prog').busy}
                    onClick={() =>
                      s?.program.recording
                        ? void runCard('prog', () => junctionCommand('program.record.stop'))
                        : void saveDialog({ defaultPath: 'Junction.wav', filters: [{ name: 'WAV', extensions: ['wav'] }] })
                            .then((path) => { if (path) void runCard('prog', () => junctionCommand('program.record.start', { path })); })
                            .catch(() => setCard('prog', { error: '保存先を選択できませんでした' }))
                    }>
                    {s?.program.recording ? '配信録音を停止' : '配信を録音'}
                  </button>
                  {isServerMode && (
                    <>
                      <button type="button" className="junction-btn junction-btn-default" disabled={cardOf('prog').busy}
                        onClick={() => void runCard('prog', () => junctionCommand('invite.rotate'))}>
                        招待を再発行（サーバー方式）
                      </button>
                      <button type="button" className="junction-btn junction-btn-default" disabled={!s?.invite}
                        onClick={() => void runCard('prog', () => copyExchangeText(s?.invite ?? ''))}>
                        招待をコピー
                      </button>
                    </>
                  )}
                </div>
                {cardOf('prog').error && <p className="junction-card-error" role="alert">{cardOf('prog').error}</p>}
              </section>
            )}

            <details className="junction-section">
              <summary>手元だけで試聴・次曲を準備</summary>
              <p className="junction-card-note">共有デッキを変更せず、ヘッドホンCUEで試聴します。</p>
              <button type="button" className="junction-btn junction-btn-default"
                onClick={() =>
                  void openAudioDialog({ multiple: false, filters: [{ name: '音源', extensions: ['mp3', 'wav', 'flac', 'aiff', 'm4a', 'ogg'] }] })
                    .then((path) => { if (typeof path === 'string') setPrivatePath(path); })
                    .catch(() => setCard('priv', { error: '音源を選択できませんでした' }))
                }>
                音源を選択
              </button>
              <p className="junction-card-note">{privatePath.split(/[\\/]/).pop() || '音源が未選択です'}</p>
              <div className="junction-card-actions">
                <button type="button" className="junction-btn junction-btn-default" disabled={cardOf('priv').busy || !privatePath}
                  onClick={() => void runCard('priv', () => junctionCommand('private.load', { path: privatePath }))}>
                  試聴へロード
                </button>
                <button type="button" className="junction-btn junction-btn-default" disabled={cardOf('priv').busy}
                  onClick={() => void runCard('priv', () => junctionCommand('private.play'))}>試聴</button>
                <button type="button" className="junction-btn junction-btn-default" disabled={cardOf('priv').busy}
                  onClick={() => void runCard('priv', () => junctionCommand('private.pause'))}>停止</button>
              </div>
              <label>
                CUE位置（秒）
                <input type="number" min={0} value={position} onChange={(e) => setPosition(Number(e.target.value))} />
              </label>
              <button type="button" className="junction-btn junction-btn-default" disabled={cardOf('priv').busy}
                onClick={() => void runCard('priv', () => junctionCommand('private.seek', { positionMs: position * 1000 }))}>
                位置を合わせる
              </button>
              {cardOf('priv').error && <p className="junction-card-error" role="alert">{cardOf('priv').error}</p>}
            </details>

            <details className="junction-section">
              <summary>接続の詳細</summary>
              <p className="junction-card-note">{s?.connection.state} · {s?.connection.detail ?? '診断情報なし'}</p>
              <p className="junction-card-note">引き継ぎ：{s?.handoffState}</p>
              <p className="junction-card-note">
                交換方式：{isServerMode ? 'サーバー（旧方式）' : '手動（招待と返答の受け渡し）'}
              </p>
            </details>

            <NetworkSettingsSection />

            <button type="button" className="junction-btn junction-btn-danger" disabled={cardOf('end').busy}
              onClick={() => void runCard('end', () => junctionCommand(host ? 'end' : 'leave'))}>
              {host ? 'セッションを終了' : '退出'}
            </button>
            {cardOf('end').error && <p className="junction-card-error" role="alert">{cardOf('end').error}</p>}
          </>
        )}
        {!active && <NetworkSettingsSection />}
      </div>
    </div>
  );
}

function peerName(s: JunctionSnapshot | null, id?: string): string {
  if (!id) return '—';
  const p = s?.participants.find((x) => x.peerId === id);
  return (p?.displayName ?? '確認中') + (id === s?.localPeerId ? '（自分）' : '');
}

function guestParticipants(s: JunctionSnapshot | null) {
  return (s?.participants ?? []).filter((p) => p.peerId !== s?.hostPeerId && (p.exchange || p.approved === false));
}

interface EntryProps {
  name: string; setName: (v: string) => void;
  sessionName: string; setSessionName: (v: string) => void;
  onFileError: (message: string) => void;
  joinText: string; setJoinText: (v: string) => void;
  outputOptions: AudioDevice[]; deviceValue: (id: string) => string;
  programDevice: string; setProgramDevice: (v: string) => void;
  adoptCurrent: boolean; setAdoptCurrent: (v: boolean) => void;
  busy: boolean; inspecting: boolean; error: string;
  preview: ExchangeInspection | null;
  onInspect: () => void; onCreate: () => void; onJoin: () => void;
}

function EntrySection(p: EntryProps) {
  const [choice, setChoice] = useState<'create' | 'join' | null>(null);
  useEffect(() => { if (p.joinText) setChoice('join'); }, [p.joinText]);
  return (
    <>
      <div className="junction-entry-actions">
        <button type="button" className={`junction-btn ${choice === 'create' ? 'junction-btn-primary' : 'junction-btn-default'}`} aria-pressed={choice === 'create'} onClick={() => setChoice('create')}>セッションを作成</button>
        <button type="button" className={`junction-btn ${choice === 'join' ? 'junction-btn-primary' : 'junction-btn-default'}`} aria-pressed={choice === 'join'} onClick={() => setChoice('join')}>招待から参加</button>
      </div>
      {!choice && <p className="junction-card-note">ホストが招待を作り、参加するDJと返答を交換します。運営の接続調整サーバーやアカウントは不要です。</p>}
      {choice && <label>
        表示名
        <input value={p.name} onChange={(e) => p.setName(e.target.value)} maxLength={80} />
      </label>}

      {choice === 'create' && <section className="junction-section">
        <h3>セッションを作成</h3>
        <p className="junction-card-note">
          運営の接続調整サーバーは不要です。作成後、DJごとに招待を作って渡します。
        </p>
        <label>
          セッション名
          <input value={p.sessionName} onChange={(e) => p.setSessionName(e.target.value)} maxLength={80} />
        </label>
        <label>
          配信先デバイス
          <select value={p.programDevice} onChange={(e) => p.setProgramDevice(e.target.value)}>
            <option value="">配信先を選択</option>
            {p.outputOptions.map((d) => (
              <option key={d.id} value={p.deviceValue(d.id)}>{d.name}</option>
            ))}
          </select>
        </label>
        <label className="junction-check">
          <input type="checkbox" checked={p.adoptCurrent} onChange={(e) => p.setAdoptCurrent(e.target.checked)} />
          現在の演奏をこのセッションで使う
        </label>
        <button type="button" className="junction-btn junction-btn-primary"
          disabled={p.busy || !p.name.trim()} onClick={p.onCreate}>
          作成
        </button>
      </section>}

      {choice === 'join' && <section className="junction-section">
        <h3>招待から参加</h3>
        <label>
          招待テキスト
          <textarea value={p.joinText} onChange={(e) => p.setJoinText(e.target.value)} rows={4} maxLength={131072} />
        </label>
        <div className="junction-card-actions">
          <button type="button" className="junction-btn junction-btn-default"
            disabled={p.inspecting || !p.joinText.trim()} onClick={p.onInspect}>
            内容を確認
          </button>
          <button type="button" className="junction-btn junction-btn-default"
            disabled={p.inspecting}
            onClick={() => {
              void readExchangeFile().then((t) => { if (t != null) p.setJoinText(t); }).catch((e) => p.onFileError(String(e)));
            }}>
            ファイルから読み込む
          </button>
          <button type="button" className="junction-btn junction-btn-default" onClick={() => void readExchangeClipboard().then(p.setJoinText).catch((e) => p.onFileError(String(e)))}>クリップボードから貼り付け</button>
        </div>
        {p.preview && (
          <div className="junction-card">
            <p className="junction-card-headline">この招待の内容</p>
            <p className="junction-card-meta">
              <span>種類：{p.preview.kind === 'invite' ? 'セッション招待' : p.preview.kind}</span>
              {p.preview.sessionName && <span>セッション：{p.preview.sessionName}</span>}
              {p.preview.hostName && <span>ホスト：{p.preview.hostName}</span>}
              {p.preview.expiresAt && <span>期限：{new Date(p.preview.expiresAt).toLocaleString()}</span>}
            </p>
            <p className="junction-card-note">
              「参加」を押すと返答テキストがこの端末で作成されます。作成しただけでは送信されません。表示に従ってホストへ渡してください。
            </p>
            <button type="button" className="junction-btn junction-btn-primary"
              disabled={p.busy || !p.name.trim() || p.preview.kind !== 'invite'} onClick={p.onJoin}>
              参加（返答を作成）
            </button>
          </div>
        )}
        {p.error && <p className="junction-card-error" role="alert">{p.error}</p>}
      </section>}
      {p.error && choice !== 'join' && <p role="alert" className="junction-card-error">{p.error}</p>}
    </>
  );
}
