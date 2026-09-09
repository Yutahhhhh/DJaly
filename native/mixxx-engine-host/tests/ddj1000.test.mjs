// End-to-end mapping -> real host. Silent fixture; no physical audio emitted.
// Opt in to the hardware route with DJALY_MIXXX_OUTPUT_DEVICE=DDJ-1000.
import test from 'node:test';
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { mkdtemp, writeFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { createInterface } from 'node:readline';
import { Ddj1000Decoder } from '../../../src/services/midi/ddj1000.ts';
import { Ddj1000Runtime } from '../../../src/services/midi/ddj1000-runtime.ts';
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
test('DDJ MIDI mapping controls real native transport, mixer, pads, scratch and cue output', { timeout: 30000 }, async () => {
  const directory = await mkdtemp(path.join(tmpdir(), 'djaly-ddj-integration-'));
  const wav = Buffer.alloc(44 + 44100 * 4 * 20);
  wav.write('RIFF'); wav.writeUInt32LE(wav.length - 8, 4); wav.write('WAVEfmt ', 8);
  wav.writeUInt32LE(16, 16); wav.writeUInt16LE(1, 20); wav.writeUInt16LE(2, 22);
  wav.writeUInt32LE(44100, 24); wav.writeUInt32LE(176400, 28); wav.writeUInt16LE(4, 32); wav.writeUInt16LE(16, 34);
  wav.write('data', 36); wav.writeUInt32LE(wav.length - 44, 40);
  const file = path.join(directory, 'silence.wav'); await writeFile(file, wav);
  const output = process.env.DJALY_MIXXX_OUTPUT_DEVICE || 'BlackHole 2ch';
  const binary = process.env.DJALY_TEST_HOST || path.resolve(import.meta.dirname, '../build-upstream/djaly-mixxx-engine-host');
  const child = spawn(binary, [], { env: { ...process.env, DJALY_MIXXX_OUTPUT_DEVICE: output, DJALY_MIXXX_RECORDING_DIR: directory } });
  let id = 0, hello, snapshot, stderr = '', runtime;
  const pending = new Map(), errors = [];
  child.stderr.on('data', bytes => { stderr += bytes; });
  const exited = new Promise(resolve => child.once('exit', resolve));
  createInterface({ input: child.stdout }).on('line', line => { const m = JSON.parse(line); if (m.kind !== 'event') pending.get(m.id)?.(m); });
  const command = async (op, params = {}) => {
    const next = ++id;
    const reply = new Promise((resolve, reject) => {
      const timer = setTimeout(() => { pending.delete(next); reject(new Error(`Timeout ${op}: ${stderr.slice(-800)}`)); }, 8000);
      pending.set(next, m => { clearTimeout(timer); pending.delete(next); m.kind === 'error' ? reject(new Error(JSON.stringify(m))) : resolve(m.data ?? m); });
    });
    child.stdin.write(JSON.stringify({ id: next, op, params, ...(hello ? { engineId: hello.engineId, sessionId: hello.sessionId } : {}) }) + '\n');
    return reply;
  };
  const refresh = async () => { snapshot = await command('state.snapshot'); return snapshot; };
  const until = async predicate => {
    for (let n = 0; n < 100; n++) { await refresh(); if (predicate(snapshot)) return; await delay(25); }
    throw new Error('State timeout: ' + JSON.stringify(snapshot));
  };
  try {
    hello = await command('session.hello'); await until(s => s.audio.applied);
    await command('deck.load', { deck: 'A', track: { trackId: 'silent', path: file, durationMs: 20000, bpm: 120, beatgridOffsetMs: 0, beatsPerBar: 4 } });
    await until(s => s.decks.A.track && s.decks.A.status !== 'loading');
    const methods = {
      play: deck => command('deck.play', { deck }), pause: deck => command('deck.pause', { deck }),
      seek: (deck, positionMs) => command('deck.seek', { deck, positionMs }),
      scratch: (deck, phase, positionMs, gestureId) => command('deck.scratch', { deck, phase, positionMs, gestureId }),
      setChannelGain: (deck, gain) => command('mixer.channel.gain', { deck, gain }),
      setCrossfader: position => command('mixer.crossfader', { position }),
      setPfl: (deck, enabled) => command('mixer.channel.pfl', { deck, enabled }),
      setEq: (deck, band, gain) => command('mixer.channel.eq', { deck, band, gain }),
      beatLoop: (deck, beats) => command('deck.loop.beats', { deck, beats }),
      enableLoop: (deck, enabled) => command('deck.loop.enable', { deck, enabled }),
      setTempo: (deck, rate) => command('deck.tempo.set', { deck, rate }),
      getDeckGeneration: () => 0, refreshSnapshot: refresh, getState: () => ({ snapshot }), getSessionId: () => hello.sessionId,
      send: command,
    };
    runtime = new Ddj1000Runtime(methods, () => ({ activate: () => {}, library: () => {}, cuePoints: { A: 0, B: 0, C: 0, D: 0 }, error: e => errors.push(e), hotcue: (deck, index, clear) => command(clear ? 'deck.hotcue.clear' : 'deck.hotcue.set', { deck, index }) }));
    const decoder = new Ddj1000Decoder();
    const input = bytes => { for (const action of decoder.feed(bytes)) runtime.dispatch(action); };
    input([0x90, 11, 127, 11, 0]); await until(s => s.decks.A.status === 'playing' && s.decks.A.positionMs > 100);
    input([0x90, 11, 127, 11, 0]); await until(s => s.decks.A.status === 'paused');
    input([0xb0, 19, 0, 51, 0]); await until(s => s.mixer.channels.A.gain === 0);
    input([0xb0, 15, 0, 47, 0]); await until(s => s.mixer.channels.A.eqLow === 0);
    input([0xb6, 31, 127, 63, 127]); await until(s => s.mixer.crossfader === 1);
    input([0x90, 0x1d, 127, 0x1d, 0]); await until(s => s.mixer.channels.A.orientation === 1);
    input([0x97, 0, 127, 0, 0]); await until(s => s.decks.A.hotCues[0] !== null);
    input([0x98, 0, 127, 0, 0]); await until(s => s.decks.A.hotCues[0] === null);
    input([0x90, 0x14, 127, 0x14, 0]); await until(s => s.decks.A.loopRegion?.enabled);
    input([0x90, 0x14, 127, 0x14, 0]); await until(s => !s.decks.A.loopRegion?.enabled);
    input([0x90, 0x36, 127]); await delay(50); input([0xb0, 0x22, 66]); await delay(50);
    // reset() dispatches the release without awaiting it, and the engine ramps
    // the platter back to playback rate before clearing the flag. Measured at
    // 100-130ms, so a fixed 100ms wait raced. Wait for the state, not a guess.
    runtime.reset(); await until(s => !s.decks.A.scratching); assert.equal(snapshot.decks.A.scratching, false);
    if (output === 'DDJ-1000') {
      assert.deepEqual(snapshot.audio.pflChannels, [2, 3]); assert.equal(snapshot.audio.pflApplied, true);
      input([0x90, 0x54, 127, 0x54, 0]); await until(s => s.mixer.channels.A.pfl);
      input([0x90, 0x54, 127, 0x54, 0]); await until(s => !s.mixer.channels.A.pfl);
    }
    assert.deepEqual(errors, []);
  } finally {
    runtime?.dispose(); await delay(100); child.stdin.end();
    const kill = setTimeout(() => child.kill('SIGTERM'), 3000);
    await exited; clearTimeout(kill); await rm(directory, { recursive: true, force: true });
  }
});
