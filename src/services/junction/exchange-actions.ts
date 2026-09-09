// UI-only: derive the meaningful next step and actions for a manual exchange
// from the shared ExchangeState. No side effects, no network. Kept here so the
// panel and any future surface stay consistent and testable.
import type {
  ExchangeState,
  JunctionParticipant,
  JunctionSnapshot,
  ParticipantExchange,
} from '../../types/junction';

export type ExchangeActionId =
  | 'copy_invite'
  | 'save_invite_file'
  | 'paste_answer'
  | 'import_answer_file'
  | 'approve'
  | 'reject'
  | 'paste_invite'
  | 'import_invite_file'
  | 'copy_answer'
  | 'save_answer_file'
  | 'retry'
  | 'reexchange'
  | 'cancel'
  | 'copy_notice'
  | 'save_notice_file'
  | 'dismiss'
  | 'open_relay';

export interface ExchangeAction {
  id: ExchangeActionId;
  label: string;
  intent: 'primary' | 'default' | 'danger';
}
export interface ExchangeGuidance {
  headline: string;
  hint?: string;
  waiting: boolean;
  error?: string;
  actions: ExchangeAction[];
}

const A: Record<ExchangeActionId, ExchangeAction> = {
  copy_invite: {id: 'copy_invite', label: '招待をコピー', intent: 'primary'},
  save_invite_file: {id: 'save_invite_file', label: '招待をファイルに保存', intent: 'default'},
  paste_answer: {id: 'paste_answer', label: '返答を貼り付けて取り込む', intent: 'primary'},
  import_answer_file: {id: 'import_answer_file', label: '返答ファイルを取り込む', intent: 'default'},
  approve: {id: 'approve', label: '参加を許可して接続', intent: 'primary'},
  reject: {id: 'reject', label: '却下', intent: 'danger'},
  paste_invite: {id: 'paste_invite', label: '新しい招待を貼り付けて取り込む', intent: 'primary'},
  import_invite_file: {id: 'import_invite_file', label: '招待ファイルを取り込む', intent: 'default'},
  copy_answer: {id: 'copy_answer', label: '返答をコピー', intent: 'primary'},
  save_answer_file: {id: 'save_answer_file', label: '返答をファイルに保存', intent: 'default'},
  retry: {id: 'retry', label: '再試行', intent: 'primary'},
  reexchange: {id: 'reexchange', label: '同じ相手に招待を作り直す', intent: 'primary'},
  cancel: {id: 'cancel', label: 'この接続操作を中止', intent: 'danger'},
  copy_notice: {id: 'copy_notice', label: '通知テキストをコピー', intent: 'default'},
  save_notice_file: {id: 'save_notice_file', label: '通知テキストを保存', intent: 'default'},
  open_relay: {id: 'open_relay', label: '中継設定を開く', intent: 'default'},
  dismiss: {id: 'dismiss', label: 'このカードを片付ける', intent: 'default'},
};

const STATE_LABEL: Record<ExchangeState, string> = {
  idle: '待機中',
  collecting: '接続情報を収集中',
  invite_ready: '招待の受け渡し待ち',
  awaiting_answer: '返答の取り込み待ち',
  approval_pending: '承認待ち',
  response_ready: '返答の受け渡し待ち',
  awaiting_host: 'ホストの確認待ち',
  connecting: '接続中',
  connected: '接続済み',
  interrupted: '接続が中断',
  needs_exchange: '再交換が必要',
  failed: '失敗',
  expired: '期限切れ',
  cancelled: '中止',
  rejected: '却下',
};

export function describeExchangeState(state: ExchangeState | undefined): string {
  return state ? STATE_LABEL[state] ?? state : '未接続';
}

/** Connection is not readiness; keep them worded apart. */
export function exchangeConnected(state: ExchangeState | undefined): boolean {
  return state === 'connected';
}

export function formatExpiry(expiresAt: number | undefined, nowMs: number): string | undefined {
  if (!expiresAt) return undefined;
  const remain = Math.round((expiresAt - nowMs) / 1000);
  if (remain <= 0) return '有効期限切れ';
  if (remain < 60) return `有効期限まで約${remain}秒`;
  return `有効期限まで約${Math.round(remain / 60)}分`;
}

function errText(x: Pick<ParticipantExchange, 'detail' | 'errorCode'>): string | undefined {
  if (x.detail) return x.detail;
  return x.detail ?? x.errorCode ?? undefined;
}

/** Host's per-card guidance for one guest peer. */
export function deriveHostCardGuidance(participant: JunctionParticipant): ExchangeGuidance {
  const x = participant.exchange;
  if (!x) return {headline: '接続の準備ができていません。', waiting: false, actions: [A.reexchange]};
  const err = errText(x);
  switch (x.state) {
    case 'idle':
    case 'collecting':
      return {headline: '接続情報をまとめています。しばらくお待ちください。', waiting: true, actions: [A.cancel]};
    case 'invite_ready':
      return {
        headline: 'この招待を相手のDJに渡してください。コピーはまだ送信ではありません。',
        hint: '手渡し・チャット・ファイルなど、確実に届く方法で共有します。',
        waiting: false,
        actions: [A.copy_invite, A.save_invite_file, A.paste_answer, A.import_answer_file, A.cancel],
      };
    case 'awaiting_answer':
      return {
        headline: '相手が作成した返答テキストを貼り付けるか、ファイルで取り込みます。',
        hint: '相手が「作成」しただけでは、ここには自動で届きません。',
        waiting: false,
        actions: [A.paste_answer, A.import_answer_file, A.copy_invite, A.cancel],
      };
    case 'approval_pending':
      return {
        headline: '返答を受け取りました。相手と内容を確認し、参加を承認すると接続します。',
        hint: '承認するまで返答は適用されません。',
        waiting: false,
        actions: [A.approve, A.reject, A.cancel],
      };
    case 'connecting':
      return {headline: '接続を確立しています。', waiting: true, actions: [A.cancel]};
    case 'connected':
      return {headline: '接続済みです。演奏を始められる状態かどうかは、下の準備状況で確認します。', waiting: false, actions: [{...A.reexchange,intent:'default'}]};
    case 'interrupted':
      return {headline: '一時的に接続が途切れました。復旧を試みています。', hint: '手動の再交換とは別に、自動で戻る場合があります。', waiting: true, actions: [A.retry, A.cancel]};
    case 'needs_exchange':
      return {headline: '再接続には新しい招待が必要です。同じ相手に招待を作り直してください。', waiting: false, actions: [A.reexchange, A.open_relay, A.cancel]};
    case 'failed':
      return {headline: '接続に失敗しました。再試行するか、招待を作り直します。', waiting: false, error: err, actions: [A.retry, A.reexchange, A.open_relay, A.cancel]};
    case 'expired':
      return {headline: '招待の有効期限が切れました。新しい招待を作り直してください。', waiting: false, actions: [A.reexchange, A.cancel]};
    case 'rejected':
      return {headline: 'この参加は却下されました。', waiting: false, actions: [A.copy_notice, A.save_notice_file, A.reexchange]};
    case 'cancelled':
      return {
        headline: 'この接続は中止されました。オフラインの相手には自動で伝わりません。',
        hint: '相手に渡せる中止通知があれば、コピーまたは保存して渡してください。',
        waiting: false,
        actions: [A.copy_notice, A.save_notice_file, A.reexchange],
      };
    default:
      return {headline: describeExchangeState(x.state), waiting: false, error: err, actions: [A.cancel]};
  }
}

/** Guest's guidance, derived from the session snapshot + own participant row. */
export function deriveGuestGuidance(snapshot: JunctionSnapshot): ExchangeGuidance {
  const self = snapshot.participants.find((p) => p.peerId === snapshot.hostPeerId);
  const x = self?.exchange;
  const sx = snapshot.exchange;
  const state = x?.state ?? sx?.state;
  const err = x ? errText(x) : sx ? errText(sx) : undefined;
  switch (state) {
    case 'idle':
    case 'collecting':
      return {headline: '音声・操作と楽曲転送の接続情報を収集しています。', waiting: true, actions: [A.cancel]};
    case 'response_ready':
      return {
        headline: '作成した返答テキストをホストへ渡してください。コピー＝送信ではありません。',
        hint: 'ホストが取り込んで承認するまで接続は始まりません。',
        waiting: false,
        actions: [A.copy_answer, A.save_answer_file, A.paste_invite, A.import_invite_file, A.cancel],
      };
    case 'awaiting_host':
      return {
        headline: 'ホストの取り込みと承認を待っています。',
        hint: 'この待機は、ホストが実際に読んだ・承認したことの証明ではありません。',
        waiting: true,
        actions: [A.copy_answer, A.save_answer_file, A.paste_invite, A.import_invite_file, A.cancel],
      };
    case 'connecting':
      return {headline: '接続を確立しています。', waiting: true, actions: [A.cancel]};
    case 'connected':
      return {headline: '接続済みです。演奏を始められる状態かどうかは、下の準備状況で確認します。', waiting: false, actions: []};
    case 'interrupted':
      return {headline: '接続が途切れました。復旧を待っています。', waiting: true, actions: [A.paste_invite, A.import_invite_file]};
    case 'needs_exchange':
      return {
        headline: '再接続には、ホストからの新しい招待を取り込む必要があります。',
        waiting: false,
        actions: [A.paste_invite, A.import_invite_file],
      };
    case 'failed':
      return {headline: '接続に失敗しました。ホストに新しい招待を発行してもらい、取り込んでください。', waiting: false, error: err, actions: [A.paste_invite, A.import_invite_file]};
    case 'expired':
      return {headline: '招待の有効期限が切れました。新しい招待を取り込んでください。', waiting: false, actions: [A.paste_invite, A.import_invite_file]};
    case 'rejected':
      return {headline: 'ホストが参加を却下しました。', waiting: false, error: err, actions: [A.paste_invite, A.import_invite_file]};
    case 'cancelled':
      return {headline: 'この接続はホストによって中止されました。', waiting: false, error: err, actions: [A.paste_invite, A.import_invite_file]};
    default:
      return {headline: describeExchangeState(state), waiting: Boolean(state), error: err, actions: []};
  }
}
