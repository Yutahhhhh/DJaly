import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { createInterface } from 'node:readline';
import { mkdtemp, writeFile, readFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import test from 'node:test';

const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
test('negative transport: scratch across zero and resume on the audio clock', { timeout: 30000 }, async () => {
  const directory = await mkdtemp(path.join(tmpdir(), 'djaly-negative-'));
  const rate = Number(process.env.DJALY_TIMING_SOURCE_RATE || 44100), wave = Buffer.alloc(44 + rate * 10 * 4);
  wave.write('RIFF'); wave.writeUInt32LE(wave.length - 8, 4); wave.write('WAVEfmt ', 8);
  wave.writeUInt32LE(16, 16); wave.writeUInt16LE(1, 20); wave.writeUInt16LE(2, 22);
  wave.writeUInt32LE(rate, 24); wave.writeUInt32LE(rate * 4, 28);
  wave.writeUInt16LE(4, 32); wave.writeUInt16LE(16, 34); wave.write('data', 36); wave.writeUInt32LE(wave.length - 44, 40);
  for (let n = 0; n < rate * 10; n++) {
    const v = Math.round(4000 * Math.sin(2 * Math.PI * 437.3 * n / rate));
    wave.writeInt16LE(v, 44 + n * 4); wave.writeInt16LE(v, 46 + n * 4);
  }
  const fixture = path.join(directory, 'tone.wav'); await writeFile(fixture, wave);
  const child = spawn(process.env.DJALY_TEST_HOST || path.resolve(import.meta.dirname, '../build-upstream/djaly-mixxx-engine-host'), [], {
    env: { ...process.env, DJALY_MIXXX_OUTPUT_DEVICE: process.env.DJALY_MIXXX_OUTPUT_DEVICE || 'BlackHole 2ch', DJALY_MIXXX_RECORDING_DIR: directory, DJALY_MIXXX_TIMING_TRACE: '1' },
  });
  let id = 0, hello, stderr = '';
  const pending = new Map();
  child.stderr.on('data', data => { stderr = (stderr + data).slice(-8000); });
  createInterface({ input: child.stdout }).on('line', line => {
    const message = JSON.parse(line); if (message.kind !== 'event') pending.get(message.id)?.(message);
  });
  async function command(op, params = {}) {
    const current = ++id;
    const reply = new Promise((resolve, reject) => {
      const timer = setTimeout(() => { pending.delete(current); reject(new Error(`${op}: ${stderr}`)); }, 5000);
      pending.set(current, message => { clearTimeout(timer); pending.delete(current); resolve(message); });
    });
    child.stdin.write(JSON.stringify({ id: current, op, params, ...(hello ? { engineId: hello.engineId, sessionId: hello.sessionId } : {}) }) + '\n');
    const message = await reply; assert.notEqual(message.kind, 'error', JSON.stringify(message)); return message.data ?? message;
  }
  async function until(predicate) {
    for (let n = 0; n < 200; n++) { const state = await command('state.snapshot'); if (predicate(state)) return state; await delay(20); }
    throw new Error(`State timeout: ${stderr}`);
  }
  const evidence = { directory, sourceRate: rate, samples: [] };
  try {
    hello = await command('session.hello'); await until(s => s.audio.applied);
    await command('deck.load', { deck: 'A', track: { trackId: 'negative', path: fixture, bpm: 120 } });
    await until(s => s.decks.A.track);
    await command('deck.seek', { deck: 'A', positionMs: 200 });
    await command('recording.start');
    const recording = (await until(s => s.recording.active)).recording;
    await delay(700);
    await command('deck.timing.trace', { deck: 'A' });
    await command('deck.play', { deck: 'A' }); await delay(100);
    const scratch = (phase, positionMs) => command('deck.scratch', { deck: 'A', phase, positionMs, gestureId: 'negative' });
    await scratch('begin', 0); await delay(30);
    for (let n = 1; n <= 40; n++) { await scratch('move', -1800 * n / 40); await delay(10); }
    await delay(100);
    const held = (await command('state.snapshot')).decks.A;
    evidence.held = held;
    evidence.heldTrace = await command('deck.timing.trace', { deck: 'A' });
    await scratch('end', -1800);
    for (let n = 0; n < 110; n++) { evidence.samples.push((await command('state.snapshot')).decks.A.positionMs); await delay(20); }
    evidence.releaseTrace = await command('deck.timing.trace', { deck: 'A' });
    console.log(JSON.stringify({ directory, held: held.positionMs, internal: evidence.heldTrace.rows.at(-1)?.positionMs, final: evidence.samples.at(-1) }));
    assert(held.positionMs < -1000, 'Published position retains negative audio position');
    assert(Math.abs(held.positionMs - evidence.heldTrace.rows.at(-1).positionMs) < 20);
    assert(evidence.samples.at(-1) > 0, 'Normal playback crosses zero without another play/seek command');
    const stable = evidence.releaseTrace.rows.slice(5);
    assert(stable.every(r => Math.abs(r.speed - 1) < .1), 'Normal rate on both sides of zero');
    assert(stable.slice(1).every((r, i) => r.positionMs > stable[i].positionMs), 'Monotonic across zero');
    assert.equal(evidence.heldTrace.dropped + evidence.releaseTrace.dropped, 0);
    await command('recording.stop'); await until(s => !s.recording.active && !s.recording.stopping);
    await delay(500);
    const recorded = await readFile(recording.path);
    let pcm, pcmRate, channels;
    for (let offset = 12; offset + 8 <= recorded.length;) {
      const length = recorded.readUInt32LE(offset + 4), name = recorded.toString('ascii', offset, offset + 4);
      if (name === 'fmt ') { pcmRate = recorded.readUInt32LE(offset + 12); channels = recorded.readUInt16LE(offset + 10); }
      if (name === 'data') pcm = recorded.subarray(offset + 8, offset + 8 + length);
      offset += 8 + length + length % 2;
    }
    assert(pcm?.length > 0);
    const samples = Array.from({ length: pcm.length / (channels * 2) }, (_, i) => pcm.readInt16LE(i * channels * 2));
    const firstAudible = samples.findIndex(v => Math.abs(v) > 30);
    const onset = evidence.heldTrace.rows.find(r => r.speed > .1);
    const crossing = stable.find(r => r.positionMs >= 0);
    assert(firstAudible >= 0 && onset && crossing);
    const expectedZeroFrame = firstAudible + (crossing.audioMs - crossing.positionMs - onset.audioMs) * pcmRate / 1000;
    const before = samples.slice(Math.round(expectedZeroFrame - pcmRate * .5), Math.round(expectedZeroFrame - pcmRate * .04));
    assert.equal(before.length, Math.round(pcmRate * .46));
    assert(before.every(v => Math.abs(v) < 10), 'Negative transport emits silence, not a frozen/repeated sample');
    const searchStart = Math.round(expectedZeroFrame - pcmRate * .04);
    const audibleAfterZero = samples.slice(searchStart).findIndex(v => Math.abs(v) > 30) + searchStart;
    evidence.pcm = { recording: recording.path, onsetErrorMs: (audibleAfterZero - expectedZeroFrame) * 1000 / pcmRate };
    assert(Math.abs(evidence.pcm.onsetErrorMs) < 20, 'PCM starts at audio-clock zero, within output buffer alignment tolerance');

    // Pausing, restarting and a tempo change use the same negative clock.
    await command('deck.pause', { deck: 'A' });
    await command('deck.seek', { deck: 'A', positionMs: -1200 }); await delay(150);
    const paused = (await command('state.snapshot')).decks.A;
    await delay(150);
    assert(Math.abs((await command('state.snapshot')).decks.A.positionMs - paused.positionMs) < .1);
    assert(Math.abs(paused.positionMs + 1200) < 1, 'Negative absolute seek is not clipped');
    await scratch('begin', 0); await delay(30);
    await scratch('move', -400); await delay(150); await scratch('end', -400); await delay(100);
    const pausedDrag = (await command('state.snapshot')).decks.A;
    assert.equal(pausedDrag.status, 'paused');
    assert(Math.abs(pausedDrag.positionMs + 1600) < 20, 'Paused scratch also operates in real negative time');
    await command('deck.tempo.set', { deck: 'A', rate: 1.2 });
    await command('deck.timing.trace', { deck: 'A' });
    await command('deck.play', { deck: 'A' }); await delay(1700);
    evidence.tempoTrace = await command('deck.timing.trace', { deck: 'A' });
    const tempoRows = evidence.tempoTrace.rows.filter(r => r.speed > .1).slice(4);
    assert(tempoRows[0].positionMs < -1000 && tempoRows.at(-1).positionMs > 0);
    assert(tempoRows.every(r => Math.abs(r.speed - 1.2) < .1), 'Tempo applies continuously before and after zero');
    console.log(JSON.stringify({ pcm: evidence.pcm, pausedPositionMs: paused.positionMs, pausedDragMs: pausedDrag.positionMs }));
  } finally {
    await writeFile(path.join(directory, 'evidence.json'), JSON.stringify(evidence, null, 2));
    child.stdin.end(); child.kill('SIGTERM');
  }
});
