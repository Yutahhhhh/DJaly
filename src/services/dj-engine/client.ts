/**
 * ネイティブ DJ エンジン（Phase 0 シミュレータ）のクライアントアダプタ。
 *
 * 既存の `<audio>` プレビュー再生（MusicPlayer / playerStore）とは別系統。
 * こちらを触っても既存の再生は影響を受けない。
 *
 * エンジンが未インストール・未起動でも例外にせず、`status()` が
 * `installed:false` / `running:false` を返して素直に劣化する。
 */

import { invoke } from "@tauri-apps/api/core";
import { listen, type UnlistenFn } from "@tauri-apps/api/event";

import {
  DJ_ENGINE_OPS,
  type DeckId,
  type EngineClientState,
  type EngineConnection,
  type EngineError,
  type EngineErrorCode,
  type EngineEventMessage,
  type EngineReply,
  type EngineSnapshot,
  type EngineStatus,
  type EqBand,
  type TrackDescriptor,
} from "@/types/dj-engine";
import {
  applySnapshotWithEvents,
  buildChannelGainParams,
  buildCrossfaderParams,
  buildEqParams,
  buildHotcueParams,
  buildLoadParams,
  buildLoopParams,
  buildMasterGainParams,
  buildMetersParams,
  buildSeekParams,
  buildTempoParams,
  createInitialClientState,
  describeEngineError,
  isEngineEventMessage,
  isEngineSnapshot,
  reduceEngineEvent,
} from "./protocol";

const EVENT_CHANNEL = "dj-engine://event";
const STATUS_CHANNEL = "dj-engine://status";

/** エンジンが返した構造化エラー。 */
export class DjEngineCommandError extends Error {
  readonly code: EngineErrorCode;
  readonly retryable: boolean;
  readonly details: unknown;

  constructor(error: EngineError) {
    super(describeEngineError(error));
    this.name = "DjEngineCommandError";
    this.code = error.code;
    this.retryable = error.retryable;
    this.details = error.details;
  }
}

const UNAVAILABLE_STATUS: EngineStatus = {
  installed: false,
  running: false,
  binaryPath: null,
  engineId: null,
  sessionId: null,
  protocol: null,
  simulated: true,
  implementation: null,
  lastError: null,
  detail:
    "Tauri 環境ではないため、ネイティブエンジンには接続できません（ブラウザ単体では利用不可）",
};

/** ブラウザ単体で開いた場合に Tauri IPC を呼ばないための判定。 */
function isTauriAvailable(): boolean {
  if (typeof window === "undefined") return false;
  return "__TAURI_INTERNALS__" in window || "__TAURI__" in window;
}

type StateListener = (state: EngineClientState) => void;
type StatusListener = (status: EngineStatus) => void;

export class DjEngineClient {
  private clientState: EngineClientState = createInitialClientState();
  private sessionId: string | null = null;
  private stateListeners = new Set<StateListener>();
  private statusListeners = new Set<StatusListener>();
  private unsubscribers: UnlistenFn[] = [];
  private attaching: Promise<void> | null = null;
  /** Events arriving while a snapshot command is in flight are replayed afterward. */
  private snapshotEventBuffer: EngineEventMessage[] | null = null;

  getState(): EngineClientState {
    return this.clientState;
  }

  getSessionId(): string | null {
    return this.sessionId;
  }

  subscribe(listener: StateListener): () => void {
    this.stateListeners.add(listener);
    return () => {
      this.stateListeners.delete(listener);
    };
  }

  subscribeStatus(listener: StatusListener): () => void {
    this.statusListeners.add(listener);
    return () => {
      this.statusListeners.delete(listener);
    };
  }

  // ---------------------------------------------------------------- ライフサイクル

  async status(): Promise<EngineStatus> {
    if (!isTauriAvailable()) return UNAVAILABLE_STATUS;
    try {
      return await invoke<EngineStatus>("dj_engine_status");
    } catch (error) {
      return { ...UNAVAILABLE_STATUS, detail: toMessage(error) };
    }
  }

  /** 明示的なオプトイン起動。既定では誰も自動起動しない。 */
  async start(outputDevice?: string): Promise<EngineStatus> {
    if (!isTauriAvailable()) return UNAVAILABLE_STATUS;
    try {
      const status = await invoke<EngineStatus>("dj_engine_start", {
        outputDevice: outputDevice?.trim() || null,
      });
      this.emitStatus(status);
      return status;
    } catch (error) {
      // start() can fail because the optional binary is absent. Re-read native
      // status instead of incorrectly claiming that it is installed.
      const current = await this.status();
      const status: EngineStatus = {
        ...current,
        lastError: current.lastError ?? toMessage(error),
        detail: current.detail ?? toMessage(error),
      };
      this.emitStatus(status);
      return status;
    }
  }

  async stop(): Promise<EngineStatus> {
    if (!isTauriAvailable()) return UNAVAILABLE_STATUS;
    const status = await invoke<EngineStatus>("dj_engine_stop");
    this.sessionId = null;
    this.clientState = createInitialClientState();
    this.emitState();
    this.emitStatus(status);
    return status;
  }

  /**
   * セッションを張り直してスナップショットを取得する。
   * webview の再読み込み後はこれを呼ぶだけで状態が復元でき、再生は止まらない。
   */
  async connect(): Promise<EngineConnection> {
    if (!isTauriAvailable()) {
      throw new Error(UNAVAILABLE_STATUS.detail ?? "エンジンを利用できません");
    }
    await this.attach();
    this.beginSnapshotBuffer();
    try {
      const connection = await invoke<EngineConnection>("dj_engine_connect");
      if (!isEngineSnapshot(connection.snapshot)) {
        throw new Error("エンジンから不正な状態スナップショットを受信しました");
      }
      this.sessionId = connection.sessionId;
      this.clientState = this.applyBufferedSnapshot(
        createInitialClientState(),
        connection.snapshot
      );
      this.emitState();
      return connection;
    } finally {
      this.snapshotEventBuffer = null;
    }
  }

  /** イベント購読を解除する。エンジンは止めない。 */
  async detach(): Promise<void> {
    const unsubscribers = this.unsubscribers;
    this.unsubscribers = [];
    this.attaching = null;
    for (const unsubscribe of unsubscribers) {
      try {
        unsubscribe();
      } catch {
        // 解除失敗は無視してよい
      }
    }
  }

  /** スナップショットを取り直す。イベント欠落を検知したときに使う。 */
  async refreshSnapshot(): Promise<EngineSnapshot> {
    this.beginSnapshotBuffer();
    try {
      const snapshot = await this.send(DJ_ENGINE_OPS.snapshot, {});
      if (!isEngineSnapshot(snapshot)) {
        throw new Error("エンジンから不正な状態スナップショットを受信しました");
      }
      this.clientState = this.applyBufferedSnapshot(this.clientState, snapshot);
      this.emitState();
      return snapshot;
    } finally {
      this.snapshotEventBuffer = null;
    }
  }

  // ---------------------------------------------------------------- 送信

  async send(op: string, params: Record<string, unknown> = {}): Promise<unknown> {
    if (!isTauriAvailable()) {
      throw new Error(UNAVAILABLE_STATUS.detail ?? "エンジンを利用できません");
    }
    const sessionId = this.sessionId;
    if (!sessionId) {
      throw new Error("エンジンに接続していません。先に connect() を呼んでください");
    }
    const reply = await invoke<EngineReply>("dj_engine_send", {
      sessionId,
      op,
      params,
    });
    if (reply.ok) {
      return reply.data;
    }
    const error: EngineError = reply.error ?? {
      code: "internal",
      message: "エンジンから理由不明のエラーが返りました",
      retryable: false,
    };
    if (error.code === "session_mismatch" || error.code === "session_required") {
      this.clientState = { ...this.clientState, sessionInvalidated: true };
      this.emitState();
    }
    throw new DjEngineCommandError(error);
  }

  // ---------------------------------------------------------------- 便利メソッド

  snapshot(): Promise<unknown> {
    return this.send(DJ_ENGINE_OPS.snapshot, {});
  }

  ping(): Promise<unknown> {
    return this.send(DJ_ENGINE_OPS.ping, {});
  }

  load(deck: DeckId, track: TrackDescriptor): Promise<unknown> {
    return this.send(DJ_ENGINE_OPS.deckLoad, buildLoadParams(deck, track));
  }

  unload(deck: DeckId): Promise<unknown> {
    return this.send(DJ_ENGINE_OPS.deckUnload, { deck });
  }

  play(deck: DeckId): Promise<unknown> {
    return this.send(DJ_ENGINE_OPS.deckPlay, { deck });
  }

  pause(deck: DeckId): Promise<unknown> {
    return this.send(DJ_ENGINE_OPS.deckPause, { deck });
  }

  seek(deck: DeckId, positionMs: number, durationMs?: number): Promise<unknown> {
    return this.send(
      DJ_ENGINE_OPS.deckSeek,
      buildSeekParams(deck, positionMs, durationMs)
    );
  }

  setTempo(deck: DeckId, rate: number): Promise<unknown> {
    return this.send(DJ_ENGINE_OPS.deckTempoSet, buildTempoParams(deck, rate));
  }

  setKeylock(deck: DeckId, enabled: boolean): Promise<unknown> {
    return this.send(DJ_ENGINE_OPS.deckKeylockSet, { deck, enabled });
  }

  setSync(deck: DeckId, enabled: boolean, leader?: DeckId): Promise<unknown> {
    return this.send(DJ_ENGINE_OPS.deckSyncSet, { deck, enabled, leader });
  }

  setHotCue(deck: DeckId, index: number, positionMs?: number): Promise<unknown> {
    return this.send(
      DJ_ENGINE_OPS.deckHotcueSet,
      buildHotcueParams(deck, index, positionMs)
    );
  }

  jumpToHotCue(deck: DeckId, index: number): Promise<unknown> {
    return this.send(DJ_ENGINE_OPS.deckHotcueJump, buildHotcueParams(deck, index));
  }

  clearHotCue(deck: DeckId, index: number): Promise<unknown> {
    return this.send(DJ_ENGINE_OPS.deckHotcueClear, buildHotcueParams(deck, index));
  }

  setLoop(deck: DeckId, startMs: number, endMs: number): Promise<unknown> {
    return this.send(DJ_ENGINE_OPS.deckLoopSet, buildLoopParams(deck, startMs, endMs));
  }

  enableLoop(deck: DeckId, enabled: boolean): Promise<unknown> {
    return this.send(DJ_ENGINE_OPS.deckLoopEnable, { deck, enabled });
  }

  setChannelGain(deck: DeckId, gain: number): Promise<unknown> {
    return this.send(
      DJ_ENGINE_OPS.mixerChannelGain,
      buildChannelGainParams(deck, gain)
    );
  }

  setEq(deck: DeckId, band: EqBand, gain: number): Promise<unknown> {
    return this.send(DJ_ENGINE_OPS.mixerChannelEq, buildEqParams(deck, band, gain));
  }

  setPfl(deck: DeckId, enabled: boolean): Promise<unknown> {
    return this.send(DJ_ENGINE_OPS.mixerChannelPfl, { deck, enabled });
  }

  setCrossfader(position: number): Promise<unknown> {
    return this.send(DJ_ENGINE_OPS.mixerCrossfader, buildCrossfaderParams(position));
  }

  setMasterGain(gain: number): Promise<unknown> {
    return this.send(DJ_ENGINE_OPS.mixerMasterGain, buildMasterGainParams(gain));
  }

  listAudioDevices(): Promise<unknown> {
    return this.send(DJ_ENGINE_OPS.audioDevicesList, {});
  }

  subscribeMeters(enabled: boolean, intervalMs?: number): Promise<unknown> {
    return this.send(
      DJ_ENGINE_OPS.metersSubscribe,
      buildMetersParams(enabled, intervalMs)
    );
  }

  // ---------------------------------------------------------------- 内部

  private attach(): Promise<void> {
    if (this.unsubscribers.length > 0) return Promise.resolve();
    if (this.attaching) return this.attaching;

    this.attaching = (async () => {
      const unsubscribeEvent = await listen<unknown>(EVENT_CHANNEL, (message) => {
        const payload = message.payload;
        if (!isEngineEventMessage(payload)) return;
        if (this.snapshotEventBuffer) {
          this.snapshotEventBuffer.push(payload);
          return;
        }
        const next = reduceEngineEvent(this.clientState, payload);
        if (next === this.clientState) return;
        this.clientState = next;
        this.emitState();
      });
      try {
        const unsubscribeStatus = await listen<unknown>(STATUS_CHANNEL, () => {
          void this.status().then((status) => this.emitStatus(status));
        });
        this.unsubscribers = [unsubscribeEvent, unsubscribeStatus];
      } catch (error) {
        unsubscribeEvent();
        throw error;
      }
    })().catch((error) => {
      // A transient registration failure must be retryable by the next connect.
      this.attaching = null;
      throw error;
    });

    return this.attaching;
  }

  private emitState(): void {
    for (const listener of this.stateListeners) {
      listener(this.clientState);
    }
  }

  private beginSnapshotBuffer(): void {
    if (this.snapshotEventBuffer) {
      throw new Error("状態スナップショットの同期はすでに実行中です");
    }
    this.snapshotEventBuffer = [];
  }

  private applyBufferedSnapshot(
    base: EngineClientState,
    snapshot: EngineSnapshot
  ): EngineClientState {
    return applySnapshotWithEvents(base, snapshot, this.snapshotEventBuffer ?? []);
  }

  private emitStatus(status: EngineStatus): void {
    for (const listener of this.statusListeners) {
      listener(status);
    }
  }
}

function toMessage(error: unknown): string {
  if (error instanceof Error) return error.message;
  return String(error);
}

/** アプリ全体で 1 つ。エンジンプロセスも 1 つだけを前提にする。 */
export const djEngineClient = new DjEngineClient();
