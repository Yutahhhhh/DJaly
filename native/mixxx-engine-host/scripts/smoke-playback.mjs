import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { createInterface } from 'node:readline';
import { mkdir, writeFile, stat } from 'node:fs/promises';
import path from 'node:path';
import { createHash } from 'node:crypto';
import { readFile } from 'node:fs/promises';

const root = path.resolve(import.meta.dirname, '..');
const output = path.join(root, 'smoke-artifacts');
await mkdir(output, { recursive: true });
const startedAt = new Date().toISOString();
const reportPath = path.join(output, process.env.DJALY_SMOKE_TWO_DECKS === '1' ? 'result-two-deck.json' : 'result.json');
await writeFile(reportPath, JSON.stringify({ passed: false, status: 'running', startedAt }));
// Generated 12-second stereo 440 Hz / 660 Hz fixture, no user media touched.
const sr = 44100, samples = sr * 12, pcm = Buffer.alloc(samples * 4);
for (let i = 0; i < samples; i++) {
  pcm.writeInt16LE(Math.round(3000 * Math.sin(2 * Math.PI * 440 * i / sr)), i * 4);
  pcm.writeInt16LE(Math.round(3000 * Math.sin(2 * Math.PI * 660 * i / sr)), i * 4 + 2);
}
const header = Buffer.alloc(44);
header.write('RIFF'); header.writeUInt32LE(36 + pcm.length, 4); header.write('WAVEfmt ', 8);
header.writeUInt32LE(16, 16); header.writeUInt16LE(1, 20); header.writeUInt16LE(2, 22);
header.writeUInt32LE(sr, 24); header.writeUInt32LE(sr * 4, 28); header.writeUInt16LE(4, 32); header.writeUInt16LE(16, 34);
header.write('data', 36); header.writeUInt32LE(pcm.length, 40);
const fixture = path.join(output, 'fixture.wav');
await writeFile(fixture, Buffer.concat([header, pcm]));
const binary = process.env.DJALY_TEST_HOST || path.join(root, 'build-upstream/djaly-mixxx-engine-host');
const binarySHA256 = createHash('sha256').update(await readFile(binary)).digest('hex');
const recordingDir = path.join(output, 'recordings');
await mkdir(recordingDir, { recursive: true });
const outputSelection = process.env.DJALY_SMOKE_DEFAULT_OUTPUT === '1'
  ? {}
  : { DJALY_MIXXX_OUTPUT_DEVICE: process.env.DJALY_MIXXX_OUTPUT_DEVICE || 'BlackHole 2ch' };
const child = spawn(binary, [], { env: { ...process.env, ...(process.env.DJALY_TRACE_LIBRARIES ? { DYLD_PRINT_LIBRARIES: '1' } : {}), ...outputSelection, DJALY_MIXXX_RECORDING_DIR: recordingDir }, stdio: ['pipe', 'pipe', 'pipe'] });
let stderr = '', id = 0, hello;
const transcript = [], queue = [], waiting = [];
child.stderr.on('data', data => { stderr += data; });
const exit = new Promise(resolve => child.on('exit', (code, signal) => resolve({ code, signal })));
createInterface({ input: child.stdout }).on('line', line => {
  const value = JSON.parse(line); transcript.push(value);
  if (waiting.length) waiting.shift()(value); else queue.push(value);
});
const next = async () => {
  if (queue.length) return queue.shift();
  return Promise.race([new Promise(resolve => waiting.push(resolve)), new Promise((_, reject) => {
    const t = setTimeout(() => reject(new Error(`Reply timeout; ${stderr.slice(-2000)}`)), 10000); t.unref();
  }), exit.then(value => { throw new Error(`Host exited ${JSON.stringify(value)}; ${stderr.slice(-2000)}`); })]);
};
async function command(op, params = {}) {
  const current = ++id;
  child.stdin.write(JSON.stringify({ protocol: 1, kind: 'command', id: current, op, params, ...(hello ? { engineId: hello.engineId, sessionId: hello.sessionId } : {}) }) + '\n');
  while (true) { const message = await next(); if (message.kind !== 'event' && message.id === current) { assert.notEqual(message.kind, 'error', JSON.stringify(message)); return message; } }
}
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
let failure, report;
try {
  hello = await command('session.hello');
  assert.equal(hello.engine.implementation, 'mixxx');
  assert.equal(hello.engine.audioAvailable, false);
  assert.equal(typeof hello.engine.audioProblem, 'string'); assert(hello.engine.audioProblem.length > 0);
  await sleep(100);
  const initialized = (await command('state.snapshot')).data;
  assert.equal(initialized.engine.audioAvailable, true, JSON.stringify(initialized.audio));
  await command('deck.load', { deck: 'A', track: { trackId: 'generated-phase1-smoke', path: fixture, durationMs: 12000 } });
  while (true) {
    const event = await next();
    assert.notEqual(event.event, 'deck.load.failed', JSON.stringify(event));
    if (event.event === 'deck.loaded') break;
  }
  await command('deck.pause', { deck: 'A' }); await sleep(150);
  assert.equal((await command('state.snapshot')).data.decks.A.status, 'paused');
  await command('deck.play', { deck: 'A' }); await sleep(1500);
  const playing = (await command('state.snapshot')).data;
  assert.equal(playing.decks.A.status, 'playing'); assert(playing.decks.A.positionMs > 700);
  const positionEvent = transcript.find(message => message.event === 'deck.position');
  assert(positionEvent, 'real engine must emit playhead telemetry');
  assert.equal(positionEvent.data.decks.A.rate, 1);
  assert.equal(typeof positionEvent.data.decks.A.positionFrames, 'number');
  assert.equal(typeof positionEvent.data.decks.A.positionMs, 'number');
  assert.equal(typeof positionEvent.data.decks.A.status, 'string');
  const { isEngineSnapshot } = await import('../../../src/services/dj-engine/protocol.ts');
  assert(isEngineSnapshot(playing), 'real snapshot must satisfy the existing TypeScript contract');
  await command('deck.pause', { deck: 'A' }); await sleep(250);
  const paused1 = (await command('state.snapshot')).data; await sleep(350);
  const paused2 = (await command('state.snapshot')).data;
  assert.equal(paused2.decks.A.status, 'paused'); assert(Math.abs(paused2.decks.A.positionMs - paused1.decks.A.positionMs) < 30);
  await command('deck.seek', { deck: 'A', positionMs: 4000 }); await sleep(350);
  const sought = (await command('state.snapshot')).data; assert(Math.abs(sought.decks.A.positionMs - 4000) < 120);
  await command('deck.play', { deck: 'A' }); await sleep(600);
  hello = await command('session.hello');
  const restored = (await command('state.snapshot')).data; assert.equal(restored.decks.A.status, 'playing'); assert(restored.decks.A.positionMs > 4300);
  let twoDeck;
  if (process.env.DJALY_SMOKE_TWO_DECKS === '1') {
    const pcmB = Buffer.alloc(samples * 4);
    for (let i = 0; i < samples; i++) {
      pcmB.writeInt16LE(Math.round(3000 * Math.sin(2 * Math.PI * 880 * i / sr)), i * 4);
      pcmB.writeInt16LE(Math.round(3000 * Math.sin(2 * Math.PI * 990 * i / sr)), i * 4 + 2);
    }
    const fixtureB = path.join(output, 'fixture-b.wav');
    await writeFile(fixtureB, Buffer.concat([header, pcmB]));
    await command('deck.load', { deck: 'B', track: { trackId: 'generated-deck-b-smoke', path: fixtureB, durationMs: 12000 } });
    while (true) {
      const event = await next(); assert.notEqual(event.event, 'deck.load.failed', JSON.stringify(event));
      if (event.event === 'deck.loaded' && event.data.deck === 'B') break;
    }
    await command('deck.play', { deck: 'B' }); await sleep(400);
    for (const deck of ['C', 'D']) {
      await command('deck.load', { deck, track: { trackId: `generated-deck-${deck}-smoke`, path: fixtureB, durationMs: 12000 } });
      while (true) {
        const event = await next(); assert.notEqual(event.event, 'deck.load.failed', JSON.stringify(event));
        if (event.event === 'deck.loaded' && event.data.deck === deck) break;
      }
      await command('deck.play', { deck });
    }
    await sleep(500);
    const both = (await command('state.snapshot')).data;
    for (const deck of ['A', 'B', 'C', 'D']) assert.equal(both.decks[deck].status, 'playing');
    await command('mixer.crossfader', { position: -1 }); await sleep(400);
    assert.equal((await command('state.snapshot')).data.mixer.crossfader, -1);
    await command('mixer.crossfader', { position: 1 }); await sleep(400);
    assert.equal((await command('state.snapshot')).data.mixer.crossfader, 1);
    await command('mixer.channel.gain', { deck: 'A', gain: 0.75 });
    await command('mixer.channel.gain', { deck: 'B', gain: 0.25 });
    await command('mixer.master.gain', { gain: 0.4 });
    const mixed = (await command('state.snapshot')).data;
    assert.equal(mixed.mixer.channels.A.gain, 0.75); assert.equal(mixed.mixer.channels.B.gain, 0.25); assert.equal(mixed.mixer.masterGain, 0.4);
    await command('recording.start'); await sleep(1500);
    const recording = (await command('state.snapshot')).data.recording;
    assert.equal(recording.active, true); assert.equal(typeof recording.path, 'string');
    await command('recording.stop'); await sleep(500);
    const recorded = (await command('state.snapshot')).data.recording;
    assert.equal(recorded.active, false); assert.equal(recorded.path, recording.path);
    assert((await stat(recorded.path)).size > 44, 'recording WAV must contain audio data');
    await command('deck.pause', { deck: 'B' }); await sleep(250);
    const bPause = (await command('state.snapshot')).data; await sleep(300);
    const separate = (await command('state.snapshot')).data;
    assert.equal(separate.decks.B.status, 'paused'); assert(Math.abs(separate.decks.B.positionMs - bPause.decks.B.positionMs) < 30);
    assert(separate.decks.A.positionMs > bPause.decks.A.positionMs + 100);
    await command('deck.unload', { deck: 'B' });
    for (const deck of ['C', 'D']) await command('deck.unload', { deck });
    twoDeck = { fourDecksPlaying: true, independentPause: true, mixerApplied: mixed.mixer, recording: { path: recorded.path, elapsedMs: recorded.elapsedMs } };
  }
  await command('deck.unload', { deck: 'A' });
  assert.equal((await command('state.snapshot')).data.decks.A.status, 'empty');
  await command('deck.load', { deck: 'A', track: { trackId: 'missing-test', path: path.join(output, 'does-not-exist.wav'), durationMs: 12000 } });
  while (true) { const message = await next(); if (message.event === 'deck.load.failed') break; }
  assert.equal((await command('state.snapshot')).data.decks.A.status, 'error');
  await command('deck.load', { deck: 'A', track: { trackId: 'cancel-test', path: fixture, durationMs: 12000 } });
  await command('deck.unload', { deck: 'A' }); await sleep(250);
  assert.equal((await command('state.snapshot')).data.decks.A.status, 'empty');
  report = { passed: true, output: playing.audio, playingMs: playing.decks.A.positionMs, pausedMs: paused2.decks.A.positionMs, soughtMs: sought.decks.A.positionMs, restoredMs: restored.decks.A.positionMs, twoDeck, missingFileFailure: true, cancelledLoadStaysEmpty: true, note: 'Transport/state evidence only; audible PCM requires the separate loopback capture.' };
} catch (error) {
  failure = error;
} finally {
  child.stdin.end();
  let outcome = await Promise.race([exit, sleep(2000).then(() => null)]);
  if (!outcome) { child.kill('SIGTERM'); outcome = await Promise.race([exit, sleep(2000).then(() => null)]); }
  if (!outcome) { child.kill('SIGKILL'); outcome = await exit; }
  await writeFile(path.join(output, 'transcript.ndjson'), transcript.map(message => JSON.stringify(message)).join('\n') + '\n');
  await writeFile(path.join(output, 'stderr.log'), stderr);
    if (failure) {
      await writeFile(reportPath, JSON.stringify({ passed: false, startedAt, binary, binarySHA256, error: String(failure), exit: outcome }, null, 2));
      throw failure;
    }
  assert.equal(outcome.code, 0, JSON.stringify(outcome));
}
await writeFile(reportPath, JSON.stringify({ ...report, startedAt, binary, binarySHA256, cleanEOF: true }, null, 2));
console.log('Real Mixxx transport smoke passed including clean EOF; evidence in', output);
