import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { createInterface } from 'node:readline';
import { mkdtemp, writeFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import test from 'node:test';

const binary = process.env.PLUMDECK_TEST_HOST || path.resolve(import.meta.dirname, '../build-upstream/plumdeck-mixxx-engine-host');
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));

test('real loaded grid correction preserves playback, pitch and track, updates native BPM and sync', { timeout: 30000 }, async () => {
  const directory = await mkdtemp(path.join(tmpdir(), 'plumdeck-beatgrid-'));
  const fixture = path.join(directory, 'grid.wav');
  const sampleRate = 44100, frameCount = sampleRate * 30;
  const wave = Buffer.alloc(44 + frameCount * 4);
  wave.write('RIFF'); wave.writeUInt32LE(wave.length - 8, 4); wave.write('WAVEfmt ', 8);
  wave.writeUInt32LE(16, 16); wave.writeUInt16LE(1, 20); wave.writeUInt16LE(2, 22);
  wave.writeUInt32LE(sampleRate, 24); wave.writeUInt32LE(sampleRate * 4, 28);
  wave.writeUInt16LE(4, 32); wave.writeUInt16LE(16, 34); wave.write('data', 36); wave.writeUInt32LE(frameCount * 4, 40);
  for (let i = 0; i < frameCount; i++) {
    const value = Math.round(1000 * Math.sin(2 * Math.PI * 440 * i / sampleRate));
    wave.writeInt16LE(value, 44 + i * 4); wave.writeInt16LE(value, 46 + i * 4);
  }
  await writeFile(fixture, wave);
  const child = spawn(binary, [], { env: { ...process.env, PLUMDECK_MIXXX_OUTPUT_DEVICE: process.env.PLUMDECK_MIXXX_OUTPUT_DEVICE || 'BlackHole 2ch' } });
  let stderr = '', id = 0, hello;
  const pending = new Map(), events = [];
  child.stderr.on('data', data => { stderr += data; });
  const exited = new Promise(resolve => child.once('exit', (code, signal) => resolve({ code, signal })));
  createInterface({ input: child.stdout }).on('line', line => {
    const message = JSON.parse(line);
    if (message.kind === 'event') events.push(message);
    else pending.get(message.id)?.(message);
  });
  async function command(op, params = {}, errorCode) {
    const current = ++id;
    const reply = new Promise((resolve, reject) => {
      const timer = setTimeout(() => { pending.delete(current); reject(new Error(`Timeout: ${op}; ${stderr.slice(-1000)}`)); }, 10000);
      pending.set(current, message => { clearTimeout(timer); pending.delete(current); resolve(message); });
    });
    child.stdin.write(JSON.stringify({ id: current, op, params, ...(hello ? { engineId: hello.engineId, sessionId: hello.sessionId } : {}) }) + '\n');
    const message = await reply;
    if (errorCode) assert.equal(message.error?.code, errorCode, JSON.stringify(message));
    else assert.notEqual(message.kind, 'error', JSON.stringify(message));
    return message;
  }
  async function until(predicate) {
    for (let i = 0; i < 100; i++) {
      const snapshot = (await command('state.snapshot')).data;
      if (predicate(snapshot)) return snapshot;
      await delay(30);
    }
    throw new Error('Snapshot condition did not become true');
  }
  try {
    hello = await command('session.hello');
    const initial = await until(snapshot => snapshot.audio.applied);
    assert(initial.engine.capabilities.includes('deck.beatgrid'));
    const request = { deck: 'A', trackId: 'grid-A', bpm: 135, firstBeatMs: 250, beatsPerBar: 3 };
    await command('deck.beatgrid.set', request, 'no_track_loaded');
    await command('deck.load', { deck: 'A', track: { trackId: 'grid-A', path: fixture, bpm: 120, beatgridOffsetMs: 125, beatsPerBar: 4 } });
    const loaded = await until(snapshot => snapshot.decks.A.track && Math.abs(snapshot.decks.A.effectiveBpm - 120) < 0.01);
    assert.equal(loaded.decks.A.track.beatgridApplied, true);
    await command('deck.tempo.set', { deck: 'A', rate: 1.1 });
    await command('deck.play', { deck: 'A' });
    const before = await until(snapshot => snapshot.decks.A.status === 'playing' && snapshot.decks.A.positionMs > 250);
    const eventCount = events.filter(event => event.event === 'deck.loaded').length;
    const accepted = (await command('deck.beatgrid.set', request)).data;
    assert.equal(accepted.track.bpm, 135); assert.equal(accepted.track.beatgridOffsetMs, 250); assert.equal(accepted.track.beatsPerBar, 3);
    const corrected = await until(snapshot => Math.abs(snapshot.decks.A.effectiveBpm - 148.5) < 0.01 && snapshot.decks.A.positionMs > before.decks.A.positionMs + 100);
    assert.equal(corrected.decks.A.status, 'playing'); assert(Math.abs(corrected.decks.A.rate - 1.1) < 0.0001);
    assert.equal(corrected.decks.A.track.trackId, 'grid-A');
    assert.equal(events.filter(event => event.event === 'deck.loaded').length, eventCount, 'Grid correction must not reload');
    assert(events.some(event => event.event === 'deck.state' && event.data.track?.bpm === 135 && Math.abs(event.data.effectiveBpm - 148.5) < 0.01));
    for (const invalid of [{ bpm: 19 }, { bpm: 301 }, { bpm: '120' }, { bpm: null }, { firstBeatMs: -1 }, { firstBeatMs: 30000 }, { firstBeatMs: null }, { beatsPerBar: 0 }, { beatsPerBar: 17 }, { beatsPerBar: 3.5 }, { trackId: 'stale-track' }, { trackId: null }]) {
      await command('deck.beatgrid.set', { ...request, ...invalid }, 'invalid_params');
    }
    const unchanged = (await command('state.snapshot')).data.decks.A;
    assert.equal(unchanged.track.bpm, 135); assert.equal(unchanged.track.beatgridOffsetMs, 250);
    // Prove the updated native Beats affect a second deck's real sync control.
    await command('deck.tempo.set', { deck: 'A', rate: 1 });
    await command('deck.load', { deck: 'B', track: { trackId: 'grid-B', path: fixture, bpm: 100, beatgridOffsetMs: 0 } });
    await until(snapshot => snapshot.decks.B.track && Math.abs(snapshot.decks.B.effectiveBpm - 100) < 0.01);
    await command('deck.sync.set', { deck: 'A', enabled: true });
    await command('deck.sync.set', { deck: 'B', enabled: true });
    await command('deck.play', { deck: 'B' });
    const synced = await until(snapshot => Math.abs(snapshot.decks.A.effectiveBpm - snapshot.decks.B.effectiveBpm) < 0.1 && Math.abs(snapshot.decks.B.rate - 1.35) < 0.01);
    console.log(JSON.stringify({ beforeMs: before.decks.A.positionMs, correctedMs: corrected.decks.A.positionMs, correctedBpm: corrected.decks.A.effectiveBpm, preservedPitch: corrected.decks.A.rate, syncBpm: synced.decks.B.effectiveBpm, syncRate: synced.decks.B.rate }));
    // Correction is also reflected while paused, when position events alone would be idle.
    await command('deck.sync.set', { deck: 'A', enabled: false });
    await command('deck.sync.set', { deck: 'B', enabled: false });
    await command('deck.pause', { deck: 'A' });
    await until(snapshot => snapshot.decks.A.status === 'paused');
    await command('deck.beatgrid.set', { ...request, bpm: 140 });
    const paused = await until(snapshot => Math.abs(snapshot.decks.A.effectiveBpm - 140) < 0.01);
    assert.equal(paused.decks.A.status, 'paused');
  } finally {
    child.stdin.end();
    const outcome = await Promise.race([exited, delay(3000).then(() => null)]);
    if (!outcome) child.kill('SIGTERM');
    await rm(directory, { recursive: true, force: true });
    assert.equal(outcome?.code, 0, stderr.slice(-1500));
  }
});
