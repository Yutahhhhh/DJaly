/**
 * フロントエンド側プロトコルロジックの契約テスト。
 *
 * 依存パッケージを増やさずに動かすため、Node 組み込みの `node:test` と
 * 型ストリップ（Node 22.6+ / 既定有効は 23.6+）だけを使う。
 *
 *   node --test native/dj-engine-host/tests-node/
 *
 * ここでは Tauri IPC には触れない。純粋関数だけを対象にする。
 */

import test from "node:test";
import assert from "node:assert/strict";

import {
  applySnapshot,
  applySnapshotWithEvents,
  buildCrossfaderParams,
  buildEqParams,
  buildLoadParams,
  buildLoopParams,
  buildTempoParams,
  createInitialClientState,
  describeEngineError,
  DjEngineValidationError,
  isEngineEventMessage,
  isEngineSnapshot,
  reduceEngineEvent,
} from "../../../src/services/dj-engine/protocol.ts";
import { DJ_ENGINE_EVENTS } from "../../../src/types/dj-engine.ts";
import type {
  DeckId,
  DeckState,
  EngineEventMessage,
  EngineSnapshot,
} from "../../../src/types/dj-engine.ts";

const ENGINE_ID = "eng-fixture";

function deckFixture(deck: DeckId): DeckState {
  return {
    deck,
    status: "ready",
    track: {
      trackId: `track-${deck}`,
      path: `/fixtures/${deck}.wav`,
      title: "Fixture",
      artist: null,
      durationMs: 200_000,
      bpm: 124,
      sampleRateHz: 44_100,
      channels: 2,
      beatgridOffsetMs: 0,
    },
    positionMs: 0,
    positionFrames: 0,
    rate: 1,
    keylock: false,
    syncEnabled: false,
    syncLeader: null,
    effectiveBpm: 124,
    hotCues: [null, null, null, null, null, null, null, null],
    loopRegion: null,
    lastError: null,
    loadId: null,
  };
}

function snapshotFixture(rev = 10): EngineSnapshot {
  return {
    rev,
    seq: 0,
    engineId: ENGINE_ID,
    sessionId: `${ENGINE_ID}-s1`,
    engineTimeMs: 0,
    engine: {
      name: "dj-engine-sim",
      version: "0.1.0",
      implementation: "simulator",
      simulated: true,
      deterministic: true,
      decks: ["A", "B"],
      capabilities: [],
    },
    decks: { A: deckFixture("A"), B: deckFixture("B") },
    mixer: {
      crossfader: 0,
      masterGain: 1,
      headphoneGain: 0.5,
      headphoneMix: 0,
      channels: {
        A: { deck: "A", gain: 1, eqLow: 1, eqMid: 1, eqHigh: 1, pfl: false },
        B: { deck: "B", gain: 1, eqLow: 1, eqMid: 1, eqHigh: 1, pfl: false },
      },
    },
    audio: {
      deviceId: null,
      sampleRateHz: 44_100,
      bufferFrames: 512,
      masterChannels: [0, 1],
      pflChannels: [2, 3],
      applied: false,
    },
    meters: { enabled: false, intervalMs: 100, simulated: true },
  };
}

function eventFixture(
  overrides: Partial<EngineEventMessage> & Pick<EngineEventMessage, "event" | "seq" | "rev">
): EngineEventMessage {
  return {
    kind: "event",
    protocol: 1,
    engineId: ENGINE_ID,
    data: {},
    engineTimeMs: 0,
    ...overrides,
  };
}

// ---------------------------------------------------------------- 検証

test("値域外のパラメータは送信前に弾かれる", () => {
  assert.throws(() => buildTempoParams("A", 10), DjEngineValidationError);
  assert.throws(() => buildTempoParams("A", 0.1), DjEngineValidationError);
  assert.throws(() => buildCrossfaderParams(-2), DjEngineValidationError);
  assert.throws(() => buildEqParams("A", "low", 99), DjEngineValidationError);
  assert.deepEqual(buildTempoParams("A", 1.05), { deck: "A", rate: 1.05 });
});

test("NaN / Infinity は境界で拒否する", () => {
  assert.throws(() => buildTempoParams("A", Number.NaN), DjEngineValidationError);
  assert.throws(
    () => buildCrossfaderParams(Number.POSITIVE_INFINITY),
    DjEngineValidationError
  );
});

test("不正なデッキ識別子は拒否する", () => {
  assert.throws(
    () => buildTempoParams("C" as unknown as DeckId, 1),
    (error: unknown) =>
      error instanceof DjEngineValidationError && error.field === "deck"
  );
});

test("ロード記述子の必須項目を検証する", () => {
  const track = {
    trackId: "t-1",
    path: "/fixtures/a.wav",
    durationMs: 200_000,
  };
  assert.deepEqual(buildLoadParams("A", track), { deck: "A", track });

  assert.throws(
    () => buildLoadParams("A", { ...track, path: "  " }),
    DjEngineValidationError
  );
  assert.throws(
    () => buildLoadParams("A", { ...track, durationMs: 0 }),
    DjEngineValidationError
  );
  assert.throws(
    () => buildLoadParams("A", { ...track, bpm: 1000 }),
    DjEngineValidationError
  );
});

test("ループは終端が始端より後でなければならない", () => {
  assert.deepEqual(buildLoopParams("A", 1000, 2000), {
    deck: "A",
    startMs: 1000,
    endMs: 2000,
  });
  assert.throws(() => buildLoopParams("A", 2000, 1000), DjEngineValidationError);
});

// ---------------------------------------------------------------- 型ガード

test("イベントメッセージの型ガード", () => {
  assert.equal(isEngineEventMessage(eventFixture({ event: "x", seq: 1, rev: 1 })), true);
  assert.equal(isEngineEventMessage(null), false);
  assert.equal(isEngineEventMessage({ kind: "result", id: 1 }), false);
  assert.equal(isEngineEventMessage({ kind: "event", event: "x" }), false);
  assert.equal(
    isEngineEventMessage(eventFixture({ event: "x", seq: 1.5, rev: 1 })),
    false
  );
  assert.equal(
    isEngineEventMessage({
      ...eventFixture({ event: "x", seq: 1, rev: 1 }),
      engineTimeMs: Number.NaN,
    }),
    false
  );
});

test("スナップショットの必須構造を境界で検証する", () => {
  assert.equal(isEngineSnapshot(snapshotFixture()), true);
  const withoutPfl = snapshotFixture();
  withoutPfl.audio.pflChannels = null;
  assert.equal(isEngineSnapshot(withoutPfl), true);
  const malformed = snapshotFixture() as unknown as Record<string, unknown>;
  malformed.decks = { A: { deck: "A", status: "ready", positionMs: 0 }, B: deckFixture("B") };
  assert.equal(isEngineSnapshot(malformed), false);
});

// ---------------------------------------------------------------- 畳み込み

test("スナップショットを適用するとリビジョンが同期する", () => {
  const state = applySnapshot(createInitialClientState(), snapshotFixture(10));
  assert.equal(state.rev, 10);
  assert.equal(state.droppedEvents, 0);
  assert.equal(state.snapshot?.decks.A.status, "ready");
});

test("スナップショット取得中はwatermarkより新しいイベントだけ再適用する", () => {
  const snapshot = { ...snapshotFixture(10), seq: 5 };
  const covered = eventFixture({
    event: DJ_ENGINE_EVENTS.deckState,
    seq: 5,
    rev: 10,
    data: { ...deckFixture("A"), status: "paused" },
  });
  const later = eventFixture({
    event: DJ_ENGINE_EVENTS.deckState,
    seq: 6,
    rev: 11,
    data: { ...deckFixture("A"), status: "playing" },
  });
  const state = applySnapshotWithEvents(
    createInitialClientState(),
    snapshot,
    [covered, later]
  );
  assert.equal(state.lastSeq, 6);
  assert.equal(state.snapshot?.decks.A.status, "playing");
});

test("別エンジンインスタンスのイベントは適用しない", () => {
  const state = applySnapshot(createInitialClientState(), snapshotFixture(10));
  const foreign = eventFixture({
    event: DJ_ENGINE_EVENTS.deckState,
    seq: 1,
    rev: 11,
    engineId: "eng-other",
    data: { ...deckFixture("A"), status: "playing" },
  });
  assert.equal(reduceEngineEvent(state, foreign), state);
});

test("重複・巻き戻しの seq は適用しない", () => {
  let state = applySnapshot(createInitialClientState(), snapshotFixture(10));
  const event = eventFixture({
    event: DJ_ENGINE_EVENTS.deckState,
    seq: 5,
    rev: 11,
    data: { ...deckFixture("A"), status: "playing" },
  });
  state = reduceEngineEvent(state, event);
  assert.equal(state.snapshot?.decks.A.status, "playing");

  // 同じ seq をもう一度
  assert.equal(reduceEngineEvent(state, event), state);
  // より古い seq
  assert.equal(reduceEngineEvent(state, { ...event, seq: 4 }), state);
});

test("seq が飛んだら取りこぼしを数える", () => {
  let state = applySnapshot(createInitialClientState(), snapshotFixture(10));
  state = reduceEngineEvent(
    state,
    eventFixture({ event: DJ_ENGINE_EVENTS.deckState, seq: 1, rev: 11, data: deckFixture("A") })
  );
  assert.equal(state.droppedEvents, 0);

  state = reduceEngineEvent(
    state,
    eventFixture({ event: DJ_ENGINE_EVENTS.deckState, seq: 5, rev: 12, data: deckFixture("A") })
  );
  assert.equal(state.droppedEvents, 3);
});

test("古いリビジョンのイベントは状態を巻き戻さない", () => {
  let state = applySnapshot(createInitialClientState(), snapshotFixture(20));
  state = reduceEngineEvent(
    state,
    eventFixture({
      event: DJ_ENGINE_EVENTS.deckState,
      seq: 1,
      rev: 15,
      data: { ...deckFixture("A"), status: "playing" },
    })
  );
  assert.equal(state.snapshot?.decks.A.status, "ready", "rev 15 < 20 なので無視される");
  assert.equal(state.lastSeq, 1, "seq だけは進む");
});

test("位置イベントはトラック情報を壊さずに位置だけ更新する", () => {
  let state = applySnapshot(createInitialClientState(), snapshotFixture(10));
  state = reduceEngineEvent(
    state,
    eventFixture({
      event: DJ_ENGINE_EVENTS.deckPosition,
      seq: 1,
      rev: 10,
      data: {
        decks: {
          A: {
            positionMs: 1234,
            positionFrames: 54_419,
            rate: 1,
            status: "playing",
          },
        },
      },
    })
  );
  assert.equal(state.snapshot?.decks.A.positionMs, 1234);
  assert.equal(state.snapshot?.decks.A.status, "playing");
  assert.equal(state.snapshot?.decks.A.track?.trackId, "track-A");
  // 触れていないデッキは変わらない
  assert.equal(state.snapshot?.decks.B.positionMs, 0);
});

test("壊れたペイロードは無視して seq だけ進める", () => {
  let state = applySnapshot(createInitialClientState(), snapshotFixture(10));
  state = reduceEngineEvent(
    state,
    eventFixture({
      event: DJ_ENGINE_EVENTS.deckState,
      seq: 1,
      rev: 11,
      data: { deck: "Z", status: "banana" },
    })
  );
  assert.equal(state.snapshot?.decks.A.status, "ready");
  assert.equal(state.lastSeq, 1);
});

test("一見妥当でも必須fieldが欠けたdeck状態は適用しない", () => {
  let state = applySnapshot(createInitialClientState(), snapshotFixture(10));
  state = reduceEngineEvent(
    state,
    eventFixture({
      event: DJ_ENGINE_EVENTS.deckState,
      seq: 1,
      rev: 11,
      data: { deck: "A", status: "playing", positionMs: 500 },
    })
  );
  assert.equal(state.snapshot?.decks.A.status, "ready");
  assert.equal(state.snapshot?.decks.A.positionMs, 0);
});

test("未知のイベントでも壊れない（前方互換）", () => {
  let state = applySnapshot(createInitialClientState(), snapshotFixture(10));
  state = reduceEngineEvent(
    state,
    eventFixture({ event: "deck.jog.touch", seq: 1, rev: 11, data: { deck: "A" } })
  );
  assert.equal(state.lastSeq, 1);
  assert.equal(state.snapshot?.rev, 10);
});

test("セッション失効はスナップショット未取得でも記録される", () => {
  const state = reduceEngineEvent(
    createInitialClientState(),
    eventFixture({
      event: DJ_ENGINE_EVENTS.sessionInvalidated,
      seq: 1,
      rev: 0,
      data: { sessionId: `${ENGINE_ID}-s1`, reason: "superseded" },
    })
  );
  assert.equal(state.sessionInvalidated, true);
});

test("遅延した旧セッションの失効通知で新セッションを失効させない", () => {
  const snapshot = { ...snapshotFixture(10), sessionId: `${ENGINE_ID}-s2` };
  const state = applySnapshot(createInitialClientState(), snapshot);
  const next = reduceEngineEvent(
    state,
    eventFixture({
      event: DJ_ENGINE_EVENTS.sessionInvalidated,
      seq: 1,
      rev: 10,
      data: { sessionId: `${ENGINE_ID}-s1`, reason: "superseded" },
    })
  );
  assert.equal(next.sessionInvalidated, false);
  assert.equal(next.lastSeq, 1);
});

test("別プロセスに繋ぎ直したら seq を振り直す", () => {
  let state = applySnapshot(createInitialClientState(), snapshotFixture(10));
  state = reduceEngineEvent(
    state,
    eventFixture({ event: DJ_ENGINE_EVENTS.deckState, seq: 42, rev: 11, data: deckFixture("A") })
  );
  assert.equal(state.lastSeq, 42);

  const restarted = { ...snapshotFixture(0), engineId: "eng-restarted" };
  state = applySnapshot(state, restarted);
  assert.equal(state.lastSeq, 0);
  assert.equal(state.meters, null);
});

// ---------------------------------------------------------------- 表示

test("エラーコードに応じた説明を返す", () => {
  assert.match(
    describeEngineError({
      code: "session_mismatch",
      message: "raw",
      retryable: false,
    }),
    /再接続/
  );
  assert.equal(
    describeEngineError({ code: "invalid_params", message: "raw", retryable: false }),
    "raw"
  );
});
