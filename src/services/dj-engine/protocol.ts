/**
 * DJ エンジンプロトコルの純粋ロジック。
 *
 * このファイルは Tauri にも React にも依存しない。
 * `node --test` から直接実行できるようにするため、副作用も持たせない。
 * （テストは `native/dj-engine-host/tests-node/protocol.test.ts`）
 */

import {
  DECK_IDS,
  DJ_ENGINE_EVENTS,
  DJ_ENGINE_RANGES,
  EQ_BANDS,
} from "../../types/dj-engine.ts";
import type {
  DeckId,
  DeckState,
  DeckStatus,
  EngineClientState,
  EngineError,
  EngineEventMessage,
  EngineSnapshot,
  EqBand,
  MetersPayload,
  TrackDescriptor,
} from "../../types/dj-engine.ts";

/** 送信前のクライアント側検証で投げるエラー。 */
export class DjEngineValidationError extends Error {
  readonly field: string;

  constructor(field: string, message: string) {
    super(message);
    this.name = "DjEngineValidationError";
    this.field = field;
  }
}

// ------------------------------------------------------------------ 検証

function assertFinite(field: string, value: number): number {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    throw new DjEngineValidationError(field, `${field} は有限の数値である必要があります`);
  }
  return value;
}

function assertRange(
  field: string,
  value: number,
  range: { min: number; max: number }
): number {
  assertFinite(field, value);
  if (value < range.min || value > range.max) {
    throw new DjEngineValidationError(
      field,
      `${field} は ${range.min} 以上 ${range.max} 以下である必要があります（指定値: ${value}）`
    );
  }
  return value;
}

export function assertDeckId(value: string): DeckId {
  if (!isDeckId(value)) {
    throw new DjEngineValidationError(
      "deck",
      `デッキは ${DECK_IDS.join(" / ")} のいずれかです（指定値: ${value}）`
    );
  }
  return value;
}

export function assertEqBand(value: string): EqBand {
  if (!EQ_BANDS.includes(value as EqBand)) {
    throw new DjEngineValidationError(
      "band",
      `band は ${EQ_BANDS.join(" / ")} のいずれかです（指定値: ${value}）`
    );
  }
  return value as EqBand;
}

// ------------------------------------------------------------------ パラメータ生成

/**
 * ロード用パラメータ。ファイルパスは **データとして** 渡すだけで、
 * シェルにも URL にも埋め込まない。
 */
export function buildLoadParams(
  deck: DeckId,
  track: TrackDescriptor
): Record<string, unknown> {
  assertDeckId(deck);
  if (!track.trackId.trim()) {
    throw new DjEngineValidationError("track.trackId", "trackId が空です");
  }
  if (!track.path.trim()) {
    throw new DjEngineValidationError("track.path", "path が空です");
  }
  assertFinite("track.durationMs", track.durationMs);
  if (track.durationMs <= 0) {
    throw new DjEngineValidationError(
      "track.durationMs",
      "durationMs は正の値である必要があります"
    );
  }
  if (track.bpm !== undefined) {
    assertRange("track.bpm", track.bpm, { min: 20, max: 300 });
  }
  return { deck, track };
}

export function buildSeekParams(
  deck: DeckId,
  positionMs: number,
  durationMs?: number
): Record<string, unknown> {
  assertDeckId(deck);
  const max = durationMs === undefined ? Number.MAX_SAFE_INTEGER : durationMs;
  assertRange("positionMs", positionMs, { min: 0, max });
  return { deck, positionMs };
}

export function buildTempoParams(deck: DeckId, rate: number): Record<string, unknown> {
  assertDeckId(deck);
  assertRange("rate", rate, DJ_ENGINE_RANGES.rate);
  return { deck, rate };
}

export function buildChannelGainParams(
  deck: DeckId,
  gain: number
): Record<string, unknown> {
  assertDeckId(deck);
  assertRange("gain", gain, DJ_ENGINE_RANGES.channelGain);
  return { deck, gain };
}

export function buildEqParams(
  deck: DeckId,
  band: EqBand,
  gain: number
): Record<string, unknown> {
  assertDeckId(deck);
  assertEqBand(band);
  assertRange("gain", gain, DJ_ENGINE_RANGES.eqGain);
  return { deck, band, gain };
}

export function buildCrossfaderParams(position: number): Record<string, unknown> {
  assertRange("position", position, DJ_ENGINE_RANGES.crossfader);
  return { position };
}

export function buildMasterGainParams(gain: number): Record<string, unknown> {
  assertRange("gain", gain, DJ_ENGINE_RANGES.masterGain);
  return { gain };
}

export function buildHotcueParams(
  deck: DeckId,
  index: number,
  positionMs?: number
): Record<string, unknown> {
  assertDeckId(deck);
  assertRange("index", index, DJ_ENGINE_RANGES.hotCueIndex);
  if (!Number.isInteger(index)) {
    throw new DjEngineValidationError("index", "index は整数である必要があります");
  }
  if (positionMs === undefined) {
    return { deck, index };
  }
  assertRange("positionMs", positionMs, { min: 0, max: Number.MAX_SAFE_INTEGER });
  return { deck, index, positionMs };
}

export function buildLoopParams(
  deck: DeckId,
  startMs: number,
  endMs: number
): Record<string, unknown> {
  assertDeckId(deck);
  assertFinite("startMs", startMs);
  assertFinite("endMs", endMs);
  if (endMs <= startMs) {
    throw new DjEngineValidationError(
      "endMs",
      "endMs は startMs より大きい必要があります"
    );
  }
  return { deck, startMs, endMs };
}

export function buildMetersParams(
  enabled: boolean,
  intervalMs?: number
): Record<string, unknown> {
  if (intervalMs === undefined) {
    return { enabled };
  }
  assertRange("intervalMs", intervalMs, DJ_ENGINE_RANGES.metersIntervalMs);
  return { enabled, intervalMs };
}

// ------------------------------------------------------------------ 型ガード

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function readNumber(record: Record<string, unknown>, key: string): number | null {
  const value = record[key];
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function isFiniteNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

function isNullableString(value: unknown): value is string | null {
  return value === null || typeof value === "string";
}

export function isDeckId(value: unknown): value is DeckId {
  return value === "A" || value === "B";
}

function isDeckStatus(value: unknown): value is DeckStatus {
  return (
    value === "empty" ||
    value === "loading" ||
    value === "ready" ||
    value === "playing" ||
    value === "paused" ||
    value === "error"
  );
}

export function isEngineEventMessage(value: unknown): value is EngineEventMessage {
  if (!isRecord(value)) return false;
  return (
    value.kind === "event" &&
    value.protocol === 1 &&
    typeof value.event === "string" &&
    typeof value.engineId === "string" &&
    typeof value.seq === "number" &&
    Number.isSafeInteger(value.seq) &&
    value.seq >= 0 &&
    typeof value.rev === "number" &&
    Number.isSafeInteger(value.rev) &&
    value.rev >= 0 &&
    typeof value.engineTimeMs === "number" &&
    Number.isFinite(value.engineTimeMs) &&
    "data" in value
  );
}

/**
 * `deck.state` のペイロードを検証する。
 * 判別に必要なフィールドだけ実際に検査し、残りは記述子として受け入れる。
 * 相手が別実装（C++ ホスト）に替わっても、壊れたイベントで UI を壊さないための境界。
 */
function parseDeckState(data: unknown): DeckState | null {
  if (!isRecord(data)) return null;
  if (!isDeckId(data.deck)) return null;
  if (!isDeckStatus(data.status)) return null;
  if (
    !isFiniteNumber(data.positionMs) ||
    !isFiniteNumber(data.positionFrames) ||
    !isFiniteNumber(data.rate) ||
    typeof data.keylock !== "boolean" ||
    typeof data.syncEnabled !== "boolean" ||
    !(data.syncLeader === null || isDeckId(data.syncLeader)) ||
    !(data.effectiveBpm === null || isFiniteNumber(data.effectiveBpm)) ||
    !Array.isArray(data.hotCues) ||
    data.hotCues.length !== 8 ||
    !data.hotCues.every((cue) => cue === null || isFiniteNumber(cue)) ||
    !isNullableString(data.lastError) ||
    !(data.loadId === null || Number.isSafeInteger(data.loadId))
  ) return null;
  if (data.track !== null) {
    if (!isRecord(data.track)) return null;
    if (
      typeof data.track.trackId !== "string" ||
      typeof data.track.path !== "string" ||
      !isNullableString(data.track.title) ||
      !isNullableString(data.track.artist) ||
      !isFiniteNumber(data.track.durationMs) ||
      !(data.track.bpm === null || isFiniteNumber(data.track.bpm)) ||
      !isFiniteNumber(data.track.sampleRateHz) ||
      !isFiniteNumber(data.track.channels) ||
      !isFiniteNumber(data.track.beatgridOffsetMs)
    ) return null;
  }
  if (data.loopRegion !== null) {
    if (!isRecord(data.loopRegion)) return null;
    if (
      !isFiniteNumber(data.loopRegion.startMs) ||
      !isFiniteNumber(data.loopRegion.endMs) ||
      typeof data.loopRegion.enabled !== "boolean"
    ) return null;
  }
  return data as unknown as DeckState;
}

function parseMixerState(data: unknown): EngineSnapshot["mixer"] | null {
  if (!isRecord(data) || !isRecord(data.channels)) return null;
  if (
    !isFiniteNumber(data.crossfader) ||
    !isFiniteNumber(data.masterGain) ||
    !isFiniteNumber(data.headphoneGain) ||
    !isFiniteNumber(data.headphoneMix)
  ) return null;
  for (const deck of DECK_IDS) {
    const channel = data.channels[deck];
    if (!isRecord(channel) || channel.deck !== deck) return null;
    if (
      !isFiniteNumber(channel.gain) ||
      !isFiniteNumber(channel.eqLow) ||
      !isFiniteNumber(channel.eqMid) ||
      !isFiniteNumber(channel.eqHigh) ||
      typeof channel.pfl !== "boolean"
    ) return null;
  }
  return data as unknown as EngineSnapshot["mixer"];
}

function isChannelPair(value: unknown): value is [number, number] {
  return Array.isArray(value) && value.length === 2 && value.every(Number.isSafeInteger);
}

function parseAudioConfig(data: unknown): EngineSnapshot["audio"] | null {
  if (!isRecord(data)) return null;
  if (
    !isNullableString(data.deviceId) ||
    !isFiniteNumber(data.sampleRateHz) ||
    !isFiniteNumber(data.bufferFrames) ||
    !isChannelPair(data.masterChannels) ||
    !(data.pflChannels === null || isChannelPair(data.pflChannels)) ||
    typeof data.applied !== "boolean" ||
    !(data.reason === undefined || typeof data.reason === "string")
  ) return null;
  return data as unknown as EngineSnapshot["audio"];
}

function parseMeters(data: unknown): MetersPayload | null {
  if (!isRecord(data) || typeof data.simulated !== "boolean" || !isRecord(data.master)) {
    return null;
  }
  if (!isFiniteNumber(data.master.peak) || !isFiniteNumber(data.master.rms)) return null;
  if (!isRecord(data.channels)) return null;
  for (const channel of Object.values(data.channels)) {
    if (
      !isRecord(channel) ||
      !isFiniteNumber(channel.peak) ||
      !isFiniteNumber(channel.rms) ||
      typeof channel.pfl !== "boolean"
    ) return null;
  }
  return data as unknown as MetersPayload;
}

export function isEngineSnapshot(value: unknown): value is EngineSnapshot {
  if (!isRecord(value) || !isRecord(value.engine) || !isRecord(value.decks)) return false;
  if (
    !Number.isSafeInteger(value.rev) ||
    !Number.isSafeInteger(value.seq) ||
    typeof value.engineId !== "string" ||
    !isNullableString(value.sessionId) ||
    !isFiniteNumber(value.engineTimeMs) ||
    typeof value.engine.name !== "string" ||
    typeof value.engine.version !== "string" ||
    typeof value.engine.implementation !== "string" ||
    typeof value.engine.simulated !== "boolean" ||
    typeof value.engine.deterministic !== "boolean" ||
    !(value.engine.audioAvailable === undefined || typeof value.engine.audioAvailable === "boolean") ||
    !Array.isArray(value.engine.decks) ||
    !Array.isArray(value.engine.capabilities)
  ) return false;
  return (
    parseDeckState(value.decks.A) !== null &&
    parseDeckState(value.decks.B) !== null &&
    parseMixerState(value.mixer) !== null &&
    parseAudioConfig(value.audio) !== null &&
    isRecord(value.meters) &&
    typeof value.meters.enabled === "boolean" &&
    isFiniteNumber(value.meters.intervalMs) &&
    typeof value.meters.simulated === "boolean"
  );
}

interface DeckPositionUpdate {
  positionMs: number;
  positionFrames: number;
  rate: number;
  status: DeckStatus;
}

function parseDeckPositions(
  data: unknown
): Partial<Record<DeckId, DeckPositionUpdate>> | null {
  if (!isRecord(data)) return null;
  const decks = data.decks;
  if (!isRecord(decks)) return null;

  const parsed: Partial<Record<DeckId, DeckPositionUpdate>> = {};
  for (const deckId of DECK_IDS) {
    const entry = decks[deckId];
    if (!isRecord(entry)) continue;
    const positionMs = readNumber(entry, "positionMs");
    const positionFrames = readNumber(entry, "positionFrames");
    const rate = readNumber(entry, "rate");
    if (positionMs === null || positionFrames === null || rate === null) continue;
    if (!isDeckStatus(entry.status)) continue;
    parsed[deckId] = { positionMs, positionFrames, rate, status: entry.status };
  }
  return parsed;
}

// ------------------------------------------------------------------ 状態の畳み込み

export function createInitialClientState(): EngineClientState {
  return {
    snapshot: null,
    rev: 0,
    lastSeq: 0,
    droppedEvents: 0,
    meters: null,
    sessionInvalidated: false,
  };
}

/** 取得したスナップショットを正本として置き換える。 */
export function applySnapshot(
  state: EngineClientState,
  snapshot: EngineSnapshot
): EngineClientState {
  // `seq` is the event watermark included in this authoritative snapshot.
  const sameEngine = state.snapshot?.engineId === snapshot.engineId;
  return {
    snapshot,
    rev: snapshot.rev,
    lastSeq: snapshot.seq,
    droppedEvents: 0,
    meters: sameEngine ? state.meters : null,
    sessionInvalidated: false,
  };
}

/** Apply a snapshot watermark, then replay only events generated afterward. */
export function applySnapshotWithEvents(
  state: EngineClientState,
  snapshot: EngineSnapshot,
  events: readonly EngineEventMessage[]
): EngineClientState {
  let next = applySnapshot(state, snapshot);
  for (const event of events) {
    if (event.engineId === snapshot.engineId && event.seq > snapshot.seq) {
      next = reduceEngineEvent(next, event);
    }
  }
  return next;
}

/**
 * イベントを 1 件適用する。
 *
 * 規則:
 * - 別エンジンインスタンスのイベントは捨てる。
 * - `seq` が戻る／重複するイベントは適用しない。
 * - `seq` が飛んだら `droppedEvents` を積む（呼び出し側がスナップショットを取り直す合図）。
 * - `rev` がクライアント側より古いイベントは状態を上書きしない。
 */
export function reduceEngineEvent(
  state: EngineClientState,
  event: EngineEventMessage
): EngineClientState {
  if (state.snapshot && event.engineId !== state.snapshot.engineId) {
    return state;
  }
  if (event.seq <= state.lastSeq) {
    return state;
  }

  const dropped =
    state.lastSeq > 0 && event.seq > state.lastSeq + 1
      ? state.droppedEvents + (event.seq - state.lastSeq - 1)
      : state.droppedEvents;

  const next: EngineClientState = {
    ...state,
    lastSeq: event.seq,
    droppedEvents: dropped,
  };

  if (event.event === DJ_ENGINE_EVENTS.sessionInvalidated) {
    const invalidatedSession = isRecord(event.data)
      ? event.data.sessionId
      : undefined;
    const activeSession = state.snapshot?.sessionId;
    // The hello reply and this event use separate delivery paths. A delayed
    // invalidation for s1 must never invalidate an already-applied s2 snapshot.
    if (
      typeof invalidatedSession === "string" &&
      typeof activeSession === "string" &&
      invalidatedSession !== activeSession
    ) {
      return next;
    }
    return { ...next, sessionInvalidated: true };
  }

  const snapshot = next.snapshot;
  if (!snapshot) {
    // スナップショット未取得。イベントだけでは状態を組み立てない。
    return next;
  }
  if (event.rev < next.rev) {
    return next;
  }

  switch (event.event) {
    case DJ_ENGINE_EVENTS.deckState: {
      const deckState = parseDeckState(event.data);
      if (!deckState) return next;
      const decks = { ...snapshot.decks };
      decks[deckState.deck] = deckState;
      return {
        ...next,
        rev: event.rev,
        snapshot: {
          ...snapshot,
          rev: event.rev,
          engineTimeMs: event.engineTimeMs,
          decks,
        },
      };
    }
    case DJ_ENGINE_EVENTS.deckPosition: {
      const positions = parseDeckPositions(event.data);
      if (!positions) return next;
      const decks = { ...snapshot.decks };
      for (const deckId of DECK_IDS) {
        const update = positions[deckId];
        if (!update) continue;
        decks[deckId] = { ...decks[deckId], ...update };
      }
      return {
        ...next,
        rev: event.rev,
        snapshot: { ...snapshot, rev: event.rev, engineTimeMs: event.engineTimeMs, decks },
      };
    }
    case DJ_ENGINE_EVENTS.mixerState: {
      const mixer = parseMixerState(event.data);
      if (!mixer) return next;
      return {
        ...next,
        rev: event.rev,
        snapshot: {
          ...snapshot,
          rev: event.rev,
          mixer,
        },
      };
    }
    case DJ_ENGINE_EVENTS.audioConfig: {
      const audio = parseAudioConfig(event.data);
      if (!audio) return next;
      return {
        ...next,
        rev: event.rev,
        snapshot: {
          ...snapshot,
          rev: event.rev,
          audio,
        },
      };
    }
    case DJ_ENGINE_EVENTS.meters: {
      const meters = parseMeters(event.data);
      if (!meters) return next;
      return { ...next, meters };
    }
    default:
      // 未知のイベントは seq だけ進めて無視する（前方互換）。
      return next;
  }
}

// ------------------------------------------------------------------ 表示

export function describeEngineError(error: EngineError): string {
  switch (error.code) {
    case "session_mismatch":
    case "session_required":
      return "エンジンとの接続が切れています。再接続してください。";
    case "engine_mismatch":
      return "別のエンジンインスタンス宛の操作です。再接続してください。";
    case "engine_exited":
      return "エンジンプロセスが終了しました。";
    case "no_track_loaded":
      return "デッキに曲がロードされていません。";
    case "track_not_ready":
      return "ロード中です。完了までお待ちください。";
    case "unsupported_operation":
      return `この実装では未対応の操作です: ${error.message}`;
    case "unknown_op":
      return `エンジンが知らない操作です: ${error.message}`;
    default:
      return error.message;
  }
}
