import React, { useState } from "react";
import { createRoot } from "react-dom/client";
import "../src/index.css";
import "../src/components/play/play-workspace.css";
import "../src/components/play/play-density.css";
import { AudioSettings } from "../src/components/play/AudioSettings";
import { RecordingSaveDialog } from "../src/components/play/RecordingSaveDialog";
import { RekordboxCueImportButton } from "../src/components/play/RekordboxCueImportButton";
import { djEngineClient } from "../src/services/dj-engine/client";
import { DEFAULT_MICROPHONE } from "../src/services/dj-engine/audio-settings";
import type { RecordingEntry } from "../src/services/play";

Object.assign(djEngineClient, {
  status: async () => ({ running: true }),
  getSessionId: () => "fixture-session",
  listAudioDevices: async () => ({ devices: [
    { id: "coreaudio:1", name: "Studio Output", displayName: "Studio Output", outputChannels: 4, inputChannels: 0, isDefault: true },
    { id: "coreaudio:2", name: "USB Microphone", displayName: "USB Microphone", outputChannels: 0, inputChannels: 2, isDefaultInput: true },
  ] }),
  send: async () => ({ deviceId: "Studio Output", sampleRateHz: 44100, bufferFrames: 512, applied: true,
    masterChannels: [0, 1], microphone: { ...DEFAULT_MICROPHONE, available: true, applied: false, level: 0 } }),
});
const recording: RecordingEntry = { id: 123, recording_key: "test", session_id: null, filepath: "/tmp/test.wav", started_at: "2026-09-08", ended_at: "2026-09-08", duration_ms: 3000, status: "completed", error: null, artist: "", title: "" };
function Fixture() {
  const [dialog, setDialog] = useState<string | null>(null);
  const [events, setEvents] = useState<unknown[]>([]);
  const record = (event: unknown) => setEvents(old => [...old, event]);
  return <main className="dj-workspace" style={{ height: "100vh", padding: 24 }}>
    <div className="flex gap-3"><button className="dj-button" onClick={() => setDialog("audio")}>音声設定を開く</button>
      <button className="dj-button" onClick={() => setDialog("recording")}>録音保存を開く</button>
      <RekordboxCueImportButton onImport={async () => { record({ import: "all" }); return { imported: 125, skipped: 8, failed: 0, conflicts: 0, errors: [], errors_truncated: 0 }; }} /></div>
    {dialog === "audio" && <AudioSettings onClose={() => setDialog(null)} onApply={async (output, microphone) => { record({ output, microphone }); }} />}
    <RecordingSaveDialog recording={dialog === "recording" ? recording : null} onClose={() => setDialog(null)} onSettled={() => record({ settled: true })}
      onBeforePreview={async () => { record({ pausedDecks: true }); await new Promise(resolve => setTimeout(resolve, 150)); }} />
    <output id="events" hidden>{JSON.stringify(events)}</output>
  </main>;
}
createRoot(document.getElementById("root")!).render(<Fixture />);
