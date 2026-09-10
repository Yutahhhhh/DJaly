import {test} from 'node:test';
import assert from 'node:assert/strict';
import {
  deriveGuestGuidance,
  deriveHostCardGuidance,
  describeExchangeState,
  exchangeConnected,
  formatExpiry,
} from './exchange-actions.ts';

const peer = (exchange) => ({peerId: 'g1', displayName: 'Guest', approved: false, exchange});
const snap = (over = {}) => ({
  active: true, sessionId: 'room', sessionName: 'Night', revision: 1, epoch: '1',
  localPeerId: 'self', hostPeerId: 'host', performerPeerId: 'host', handoffState: 'IDLE',
  participants: [{peerId: 'self', displayName: 'Me'}], readiness: {ready: false, reasons: []},
  program: {state: 'preparing'}, connection: {state: 'connected'}, ...over,
});

test('host: invite_ready offers copy/save and is honest that copy is not send', () => {
  const g = deriveHostCardGuidance(peer({state: 'invite_ready', waitingFor: 'guest'}));
  assert.equal(g.waiting, false);
  assert.ok(g.headline.includes('まだ送信ではありません'));
  assert.deepEqual(g.actions.map((a) => a.id), ['copy_invite', 'save_invite_file', 'paste_answer', 'import_answer_file', 'cancel']);
});

test('host: approval happens before the answer is applied', () => {
  const g = deriveHostCardGuidance(peer({state: 'approval_pending', waitingFor: 'host'}));
  assert.ok(g.actions.some((a) => a.id === 'approve'));
  assert.ok(g.actions.some((a) => a.id === 'reject'));
  assert.ok(/承認するまで/.test(g.hint ?? ''));
});

test('host: needs_exchange keeps the card and points at re-inviting the same peer', () => {
  const g = deriveHostCardGuidance(peer({state: 'needs_exchange', waitingFor: 'none'}));
  assert.deepEqual(g.actions.map((a) => a.id), ['reexchange', 'open_relay', 'cancel']);
});

test('host: failed surfaces error text next to the next action', () => {
  const g = deriveHostCardGuidance(peer({state: 'failed', waitingFor: 'none', detail: '相手が応答しません', errorCode: 'ICE_TIMEOUT'}));
  assert.equal(g.error, '相手が応答しません');
  assert.ok(g.actions.some((a) => a.id === 'retry'));
});

test('host: cancelled provides a transferable notice because offline peers are not notified magically', () => {
  const g = deriveHostCardGuidance(peer({state: 'cancelled', waitingFor: 'none'}));
  assert.ok(g.actions.some((a) => a.id === 'copy_notice'));
  assert.ok(g.actions.some((a) => a.id === 'save_notice_file'));
  assert.ok(/自動で伝わりません/.test(g.headline));
});

test('guest: response_ready never claims copy equals sent', () => {
  const g = deriveGuestGuidance(snap({participants: [peerSelf('response_ready')]}));
  assert.ok(g.headline.includes('コピー＝送信ではありません'));
  assert.deepEqual(g.actions.map((a) => a.id), ['copy_answer', 'save_answer_file', 'paste_invite', 'import_invite_file', 'cancel']);
});

test('guest: awaiting_host is explicit that waiting is not proof the host read it', () => {
  const g = deriveGuestGuidance(snap({participants: [peerSelf('awaiting_host')]}));
  assert.equal(g.waiting, true);
  assert.ok(/証明ではありません/.test(g.hint ?? ''));
});

test('guest: needs_exchange asks to import a fresh invite', () => {
  const g = deriveGuestGuidance(snap({participants: [peerSelf('needs_exchange')]}));
  assert.deepEqual(g.actions.map((a) => a.id), ['paste_invite', 'import_invite_file']);
});

test('guest: falls back to snapshot.exchange when self row has none', () => {
  const g = deriveGuestGuidance(snap({exchange: {mode: 'manual', state: 'connecting'}}));
  assert.equal(g.waiting, true);
});

test('describe + connected wording is distinct from readiness', () => {
  assert.equal(describeExchangeState('connected'), '接続済み');
  assert.equal(exchangeConnected('connected'), true);
  assert.equal(exchangeConnected('connecting'), false);
});

test('formatExpiry is coarse and never a fake percentage', () => {
  const now = 1_000_000;
  assert.equal(formatExpiry(undefined, now), undefined);
  assert.equal(formatExpiry(now - 1, now), '有効期限切れ');
  assert.equal(formatExpiry(now + 30_000, now), '有効期限まで約30秒');
  assert.equal(formatExpiry(now + 600_000, now), '有効期限まで約10分');
});

function peerSelf(state) {
  return {peerId: 'host', displayName: 'Host', exchange: {state, waitingFor: 'local'}};
}
