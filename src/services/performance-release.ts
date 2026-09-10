import { checkJunctionActive } from './junction/client';
import { invoke, isTauri } from "@tauri-apps/api/core";
import { djEngineClient } from "@/services/dj-engine/client";
import { DECK_IDS } from "@/types/dj-engine";
import type { MidiStatus } from "@/hooks/useDdj1000";

export interface ReleaseOutcome {
  /** True once nothing of ours is holding an audio output stream. */
  audioReleased: boolean;
  /** True once the controller ports are closed (or there were none). */
  midiReleased: boolean;
  problems: string[];
}

// `dj_midi_status` returns the snapshot from *before* the worker applies the
// lease, so a single call cannot confirm the ports closed. Re-ask until the
// snapshot itself reports disconnected, with the native 3 s lease expiry as the
// backstop we are trying not to wait for.
const MIDI_POLL_INTERVAL_MS = 60;
const MIDI_POLL_TIMEOUT_MS = 3_500;

const wait = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

/** Flushes an in-progress recording so leaving Play never truncates a file. */
async function flushRecording(problems: string[]): Promise<void> {
  if (!djEngineClient.getSessionId()) return;
  if (!djEngineClient.getState().snapshot?.recording?.active) return;
  try {
    await djEngineClient.stopRecording();
  } catch (error) {
    problems.push(`録音を終了できませんでした: ${String(error)}`);
  }
}

/**
 * Pauses every deck but keeps the engine process alive and reconnectable.
 *
 * This is the Play → 解析 path: the DJ is still inside plumdeck, so tearing the
 * engine down would make going back cost a full restart.
 */
export async function suspendPerformanceAudio(): Promise<ReleaseOutcome> {
  if (await checkJunctionActive()) return {audioReleased: true, midiReleased: true, problems: []};
  const problems: string[] = [];
  await flushRecording(problems);
  if (!djEngineClient.getSessionId()) {
    try {
      await djEngineClient.stop();
      return { audioReleased: true, midiReleased: true, problems };
    } catch (error) {
      problems.push(`ネイティブエンジンを停止できませんでした: ${String(error)}`);
      return { audioReleased: false, midiReleased: true, problems };
    }
  }
  const outcomes = await Promise.allSettled(DECK_IDS.map((deck) => djEngineClient.pause(deck)));
  if (outcomes.some((outcome) => outcome.status === "rejected")) {
    try {
      await djEngineClient.stop();
    } catch (error) {
      problems.push(`ネイティブエンジンを停止できませんでした: ${String(error)}`);
      return { audioReleased: false, midiReleased: true, problems };
    }
  }
  return { audioReleased: true, midiReleased: true, problems };
}

/**
 * Hands the audio device and the controller back to rekordbox.
 *
 * Assist mode is a passive observer of rekordbox, so pausing the decks is not
 * enough: a paused engine still holds its output stream open, and the DDJ ports
 * stay leased until the native worker applies the release. Both are torn down
 * and confirmed before assist mode is shown.
 */
export async function releasePerformanceHardware(): Promise<ReleaseOutcome> {
  if (await checkJunctionActive()) return {audioReleased: false, midiReleased: false, problems: ["Junctionから退出またはセッションを終了してください。"]};
  const problems: string[] = [];
  await flushRecording(problems);

  let audioReleased = true;
  try {
    await djEngineClient.stop();
  } catch (error) {
    audioReleased = false;
    problems.push(
      `ネイティブエンジンを停止できませんでした。rekordbox がオーディオデバイスを掴めない可能性があります: ${String(error)}`,
    );
  }

  const midiReleased = await releaseMidi(problems);
  return { audioReleased, midiReleased, problems };
}

async function releaseMidi(problems: string[]): Promise<boolean> {
  if (!isTauri()) return true;
  const deadline = Date.now() + MIDI_POLL_TIMEOUT_MS;
  let lastError: unknown = null;
  while (Date.now() < deadline) {
    try {
      const status = await invoke<MidiStatus>("dj_midi_status", { enabled: false });
      if (!status.connected && !status.enabled && !status.display?.midiOpen && !status.display?.hidOpen) return true;
    } catch (error) {
      lastError = error;
    }
    await wait(MIDI_POLL_INTERVAL_MS);
  }
  problems.push(
    lastError
      ? `MIDI コントローラーを解放できませんでした: ${String(lastError)}`
      : "MIDI コントローラーの解放を確認できませんでした（数秒後に自動解放されます）",
  );
  return false;
}
