import { useEffect, useRef, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { djEngineClient } from "@/services/dj-engine/client";
import { Ddj1000Decoder, ddj1000Feedback, ddj1000ExtendedFeedback } from "@/services/midi/ddj1000";
import { Ddj1000Runtime, type ControllerActions } from "@/services/midi/ddj1000-runtime";
import { sampler } from "@/services/dj-engine/sampler";
import { padSelectionFeedback } from "@/services/midi/pad-state";
import { JOG_DEFAULT, jogSetting } from "@/services/midi/jog-settings";
import { coloredPadFeedback } from "@/services/midi/pad-colors";
import { jogFrame, isJogScreenMidi, type JogAssets } from "@/services/midi/ddj1000-display";
import { loadJogAssets } from "@/services/midi/ddj1000-display-assets";
export type MidiStatus = { enabled: boolean; connected: boolean; generation: number; device: string | null; received: number; sent: number; error: string | null;
  display?: { midiOpen: boolean; hidOpen: boolean; authenticated: boolean; reportsSent: number; error: string | null } };
const OFF: MidiStatus = { enabled: false, connected: false, generation: 0, device: null, received: 0, sent: 0, error: null };
export function useDdj1000(actions: ControllerActions) {
  const latest = useRef(actions); latest.current = actions;
  const [enabled, setEnabled] = useState(() => localStorage.getItem("djaly.ddj1000.enabled") !== "false");
  const [status, setStatus] = useState<MidiStatus>(OFF);
  const [retry, setRetry] = useState(0);
  const lightTestUntil = useRef(0);
  const [sensitivity, setSensitivity] = useState(() => {
    return jogSetting(Number(localStorage.getItem("djaly.ddj1000.jogSensitivity") ?? JOG_DEFAULT),localStorage.getItem("djaly.ddj1000.jogSensitivityVersion"));
  });
  const sensitivityRef = useRef(sensitivity); sensitivityRef.current = sensitivity;
  useEffect(() => { localStorage.setItem("djaly.ddj1000.enabled", String(enabled)); }, [enabled]);
  useEffect(() => {
    const next=jogSetting(sensitivity,localStorage.getItem("djaly.ddj1000.jogSensitivityVersion"));
    sensitivityRef.current=next;
    if(next!==sensitivity) setSensitivity(next);
    localStorage.setItem("djaly.ddj1000.jogSensitivity",String(next));
    localStorage.setItem("djaly.ddj1000.jogSensitivityVersion","4");
  }, [sensitivity]);
  useEffect(() => {
    if (!("__TAURI_INTERNALS__" in window || "__TAURI__" in window)) { setStatus({ ...OFF, error: "MIDI接続はデスクトップ版で利用できます" }); return; }
    let live = true, polling = false, writing = false, initialized = false;
    let connection = OFF, engineSession = djEngineClient.getSessionId();
    const decoder = new Ddj1000Decoder();
    const runtime = new Ddj1000Runtime(djEngineClient, () => latest.current);
    for (const deck of ["A", "B", "C", "D"] as const) runtime.setTempoRange(deck, Number(localStorage.getItem(`djaly.tempoRange.${deck}`)) || 16);
    const tempoRange = (event: Event) => {
      const detail = (event as CustomEvent<{ deck: import("@/types/dj-engine").DeckId; range: number }>).detail;
      runtime.setTempoRange(detail.deck, detail.range);
    };
    window.addEventListener("djaly:controller-tempo-range", tempoRange);
    const sent = new Map<string, number>();
    let refreshFeedbackAt = 0;
    let reading = false;
    let displayWriting = false;
    const displayAssets = new Map<string, { token: string; assets?: JogAssets }>();
    const reset = () => { decoder.reset(); runtime.reset(); sent.clear(); initialized = false; };
    const poll = async () => {
      if (!live || polling) return; polling = true;
      try {
        const next = await invoke<MidiStatus>("dj_midi_status", { enabled });
        if (!live) return;
        if (connection.generation !== next.generation || connection.connected !== next.connected) reset();
        connection = next; setStatus(next);
        if (enabled && next.connected && !initialized) {
          // DDJ-1000 PC APP CONNECT: request the current hardware controls.
          // Install the listener and generation first, or the reply is lost.
          await invoke("dj_midi_send", { generation: next.generation, messages: [[0x9f, 0x09, 0x7f]] });
          if (live && connection.generation === next.generation) initialized = true;
        }
      } catch (e) { if (live) { reset(); connection = OFF; setStatus({ ...OFF, error: String(e) }); } }
      finally { polling = false; }
    };
    void poll();
    const inputTimer = setInterval(() => {
      if (!live || !enabled || !connection.connected || reading) return;
      reading = true;
      void invoke<{ generation: number; messages: number[][] }[]>("dj_midi_read").then(events => {
        if (!live) return;
        runtime.jogSensitivity = sensitivityRef.current;
        for (const event of events) {
          if (!connection.connected || event.generation !== connection.generation) continue;
          for (const bytes of event.messages) for (const action of decoder.feed(bytes)) runtime.dispatch(action);
        }
      }).catch(e => {
        if (live) { reset(); connection = OFF; setStatus({ ...OFF, error: String(e) }); }
      }).finally(() => { reading = false; });
    }, 4); // Match the MIDI worker cadence; frame-rate polling adds latency to cuts.
    const pollTimer = setInterval(() => void poll(), 500);
    const displayTimer = setInterval(() => {
      if (!live || !enabled || !connection.connected || displayWriting) return;
      const snapshot = djEngineClient.getState().snapshot;
      const decks = (["A", "B", "C", "D"] as const).map(id => {
        const deck = snapshot?.decks[id];
        const token = deck?.track ? `${djEngineClient.getSessionId()}:${id}:${djEngineClient.getDeckGeneration(id)}:${deck.track.trackId}` : "";
        let entry = displayAssets.get(id);
        if (!entry || entry.token !== token) {
          entry = { token }; displayAssets.set(id, entry);
          const target = entry, trackId = Number(deck?.track?.trackId);
          if (token && Number.isFinite(trackId) && trackId > 0) void loadJogAssets(trackId).then(assets => {
            if (live && displayAssets.get(id) === target) target.assets = assets;
          }).catch(e => { if (live && displayAssets.get(id) === target) latest.current.error(`ジョグ画面の画像取得: ${String(e)}`); });
        }
        return jogFrame(deck, token, entry.assets);
      });
      displayWriting = true;
      void invoke("dj_jog_display_update", { generation: connection.generation, decks })
        .catch(e => { if (live) setStatus(previous => ({ ...previous, error: String(e) })); })
        .finally(() => { displayWriting = false; });
    }, 50);
    const feedbackTimer = setInterval(() => {
      if (!live || !enabled || !connection.connected || !initialized || writing) return;
      const session = djEngineClient.getSessionId();
      if (session !== engineSession) { reset(); engineSession = session; }
      // MIDI output has no delivery acknowledgement. Re-send static LEDs too
      // so a late hardware startup cannot leave an OS-accepted frame cached forever.
      if (Date.now() >= refreshFeedbackAt) { sent.clear(); refreshFeedbackAt = Date.now() + 2000; }
      const messages = coloredPadFeedback([...ddj1000Feedback(djEngineClient.getState().snapshot, djEngineClient.getState().meters), ...ddj1000ExtendedFeedback(djEngineClient.getState().snapshot, sampler.getSnapshot()), ...padSelectionFeedback()],djEngineClient.getState().snapshot,latest.current.cueColors,sampler.getSnapshot())
        .filter(message => !connection.display?.hidOpen || !isJogScreenMidi(message))
        .map(message => lightTestUntil.current > Date.now() && message[0] >= 0x90 && message[0] <= 0x93 && message[1] === 0x0c
          ? [message[0], message[1], Math.floor(Date.now() / 500) % 2 ? 127 : 0] : message)
        .filter(([s, k, v]) => sent.get(`${s}:${k}`) !== v);
      if (!messages.length) return;
      writing = true;
      const generation = connection.generation;
      void (async () => {
        for (let offset = 0; offset < messages.length; offset += 128) {
          if (!live || generation !== connection.generation) return;
          const batch = messages.slice(offset, offset + 128);
          await invoke("dj_midi_send", { generation, messages: batch });
          if (live && generation === connection.generation) for (const [s,k,v] of batch) sent.set(`${s}:${k}`,v);
        }
      })().catch(e => { if (live) setStatus(previous => ({ ...previous, error: String(e) })); }).finally(() => { writing = false; });
    }, 50);
    return () => {
      live = false; clearInterval(displayTimer); clearInterval(inputTimer); clearInterval(pollTimer); clearInterval(feedbackTimer); window.removeEventListener("djaly:controller-tempo-range", tempoRange); runtime.dispose();
      // The native lease closes the ports and clears feedback itself. Avoid a
      // delayed cleanup disabling the next effect after a reconnect.
      void invoke("dj_midi_status", { enabled: false }).catch(() => undefined);
    };
  }, [enabled, retry]);
  return { status, enabled, setEnabled, sensitivity, setSensitivity,
    reconnect: () => setRetry(value => value + 1),
    testLights: () => { lightTestUntil.current = Date.now() + 4000; } };
}
