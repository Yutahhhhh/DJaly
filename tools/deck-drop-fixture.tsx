import React from "react";
import { createRoot } from "react-dom/client";
import { mockIPC, mockWindows } from "@tauri-apps/api/mocks";
import { emit } from "@tauri-apps/api/event";
import { PlayWorkspace } from "../src/components/play/PlayWorkspace";
import { djEngineClient } from "../src/services/dj-engine/client";
import { createInitialClientState } from "../src/services/dj-engine/protocol";
import { DECK_IDS, type DeckId, type EngineSnapshot, type TrackDescriptor } from "../src/types/dj-engine";
import "../src/index.css";

// Render the actual workspace, library, deck controls, mixer and waveforms.
// Only the audio engine / OS event transport is mocked; never play real audio.
mockWindows("main");
const waveformAsset = "a".repeat(64);
mockIPC((command) => command === "dj_waveform_manifest" ? {
  schemaVersion: 2, assetKey: waveformAsset, sourceSampleRateHz: 44100, channelCount: 2,
  sourceFrameOrigin: 0, sourceFrameCount: 44100 * 180, frameCountFinal: true,
  baseFramesPerBin: 64, tileBins: 2048, state: "ready", revision: 1,
  // Exact malformed shape produced by v0.5.10. The UI must normalize this
  // instead of throwing "number 0 is not iterable" after a successful load.
  levels: Array.from({ length: 10 }, (_, lod) => ({ lod, framesPerBin: 64 * 2 ** lod, readyTileRanges: [0, 1], bandReadyTileRanges: [0, 1] })),
} : undefined, { shouldMockEvents: true });
let snapshot = {
  rev: 1, seq: 1, engineId: "drop-fixture", sessionId: "drop-session", engineTimeMs: 0,
  engine: { name: "fixture", version: "1", implementation: "simulator", simulated: true, deterministic: true, decks: [...DECK_IDS],
    capabilities: ["deck.load", "deck.transport", "deck.tempo", "deck.hotcue", "deck.loop", "deck.beatjump", "deck.quantize", "deck.sync", "deck.beatgrid", "mixer.basic", "waveform.tiles.v2"] },
  decks: Object.fromEntries(DECK_IDS.map(deck => [deck, { deck, status: "empty", track: null, positionMs: 0, positionFrames: 0, rate: 1, keylock: false, syncEnabled: false, syncLeader: null, effectiveBpm: null, hotCues: Array(8).fill(null), loopRegion: null, lastError: null, loadId: null }])),
  mixer: { crossfader: 0, masterGain: 1, headphoneGain: .5, headphoneMix: 0,
    channels: Object.fromEntries(DECK_IDS.map(deck => [deck, { deck, gain: 1, eqLow: 1, eqMid: 1, eqHigh: 1, pfl: false }])) },
  audio: { deviceId: "fixture", sampleRateHz: 44100, bufferFrames: 512, masterChannels: [0, 1], pflChannels: null, applied: true },
  meters: { enabled: false, intervalMs: 100, simulated: true },
} as EngineSnapshot;
let state = { ...createInitialClientState(), snapshot };
const subscribers = new Set<(value: typeof state) => void>();
const loads: { deck: DeckId; trackId: string }[] = [];
Object.assign(djEngineClient, {
  status: async () => ({ running: true, installed: true }),
  getSessionId: () => "drop-session", getDeckGeneration: () => 1,
  getState: () => state, refreshSnapshot: async () => snapshot,
  subscribe: (fn: (value: typeof state) => void) => { subscribers.add(fn); return () => subscribers.delete(fn); },
  send: async (operation: string) => operation === "waveform.ensure" ? { assetKey: waveformAsset, state: "ready" } : {},
  load: async (deck: DeckId, descriptor: TrackDescriptor) => {
    loads.push({ deck, trackId: descriptor.trackId });
    snapshot = { ...snapshot, decks: { ...snapshot.decks, [deck]: { ...snapshot.decks[deck], status: "ready", loadGeneration: 1, track: { ...descriptor, sampleRateHz: 44100, channels: 2 } } } };
    state = { ...state, snapshot }; subscribers.forEach(fn => fn(state));
  },
});
Object.assign(window, { deckDropFixture: { loads, native: (type: string, x: number, y: number) => emit(`tauri://drag-${type}`, { paths: [], position: { x, y } }) } });
createRoot(document.getElementById("root")!).render(<div style={{ height: "100vh" }}><PlayWorkspace /></div>);
