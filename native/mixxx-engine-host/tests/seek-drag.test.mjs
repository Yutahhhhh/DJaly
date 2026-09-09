import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { createInterface } from 'node:readline';
import { mkdtemp, writeFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import test from 'node:test';

const binary = process.env.DJALY_TEST_HOST || path.resolve(import.meta.dirname, '../build-upstream/djaly-mixxx-engine-host');
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));

test('continuous 25 Hz seek drag stays responsive and leaves playback at the final request', { timeout: 30000 }, async () => {
  const directory = await mkdtemp(path.join(tmpdir(), 'djaly-seek-drag-'));
  const fixture = path.join(directory, 'seek-drag.wav');
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
  const child = spawn(binary, [], { env: { ...process.env, DJALY_MIXXX_OUTPUT_DEVICE: 'BlackHole 2ch' } });
  let stderr = '', id = 0, hello;
  const pending = new Map();
  child.stderr.on('data', data => { stderr += data; });
  const exited = new Promise(resolve => child.once('exit', (code, signal) => resolve({ code, signal })));
  createInterface({ input: child.stdout }).on('line', line => {
    const message = JSON.parse(line);
    if (message.kind !== 'event') pending.get(message.id)?.(message);
  });

  async function command(op, params = {}) {
    const current = ++id;
    const reply = new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        pending.delete(current);
        reject(new Error(`Timeout: ${op}; ${stderr.slice(-1000)}`));
      }, 10000);
      pending.set(current, message => {
        clearTimeout(timer);
        pending.delete(current);
        resolve(message);
      });
    });
    child.stdin.write(JSON.stringify({ id: current, op, params, ...(hello ? { engineId: hello.engineId, sessionId: hello.sessionId } : {}) }) + '\n');
    const message = await reply;
    assert.notEqual(message.kind, 'error', JSON.stringify(message));
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
    await until(snapshot => snapshot.audio.applied);
    await command('deck.load', { deck: 'A', track: { trackId: 'seek-drag-A', path: fixture, bpm: 120, beatgridOffsetMs: 0 } });
    await until(snapshot => snapshot.decks.A.track?.trackId === 'seek-drag-A');
    await command('deck.play', { deck: 'A' });
    await until(snapshot => snapshot.decks.A.status === 'playing' && snapshot.decks.A.positionMs > 100);

    const requestCount = 200;
    const periodMs = 40;
    const finalPositionMs = 15000;
    const operations = [];
    const responsiveness = [];
    const startedAt = performance.now();
    for (let index = 0; index < requestCount; index++) {
      const positionMs = index === requestCount - 1 ? finalPositionMs : 1000 + ((index * 347) % 18000);
      operations.push(command('deck.seek', { deck: 'A', positionMs }).then(
        reply => ({ reply }),
        error => ({ error }),
      ));
      if (index % 25 === 0) {
        for (const op of ['engine.ping', 'state.snapshot']) {
          const sentAt = performance.now();
          operations.push(command(op).then(
            reply => { responsiveness.push({ op, latencyMs: performance.now() - sentAt, reply }); return { reply }; },
            error => ({ error }),
          ));
        }
      }
      const nextAt = startedAt + (index + 1) * periodMs;
      await delay(Math.max(0, nextAt - performance.now()));
    }

    const results = await Promise.all(operations);
    const failure = results.find(result => result.error);
    if (failure) throw failure.error;
    assert.equal(responsiveness.length, 16);
    assert(responsiveness.filter(sample => sample.op === 'engine.ping').every(sample => sample.reply.data.pong === true));
    assert(responsiveness.filter(sample => sample.op === 'state.snapshot').every(sample => sample.reply.data.decks.A.status === 'playing'), 'Playback status changed during seek drag');
    const maxResponseMs = Math.max(...responsiveness.map(sample => sample.latencyMs));
    assert(maxResponseMs < 1000, `Ping/snapshot response stalled for ${maxResponseMs.toFixed(1)}ms`);

    const final = await until(snapshot => {
      const deck = snapshot.decks.A;
      return deck.status === 'playing' && deck.positionMs >= finalPositionMs - 150 && deck.positionMs <= finalPositionMs + 1000;
    });
    assert.equal(final.decks.A.status, 'playing');
    assert(Math.abs(final.decks.A.positionMs - finalPositionMs) < 1000, `Observed ${final.decks.A.positionMs}ms after final seek to ${finalPositionMs}ms`);
    console.log(JSON.stringify({
      seekRequests: requestCount,
      requestedRateHz: 1000 / periodMs,
      elapsedMs: Math.round(performance.now() - startedAt),
      responsivenessSamples: responsiveness.length,
      maxResponseMs: Number(maxResponseMs.toFixed(1)),
      finalRequestedMs: finalPositionMs,
      finalObservedMs: final.decks.A.positionMs,
      finalStatus: final.decks.A.status,
    }));
  } finally {
    child.stdin.end();
    let outcome = await Promise.race([exited, delay(3000).then(() => null)]);
    if (!outcome) {
      child.kill('SIGTERM');
      outcome = await Promise.race([exited, delay(3000).then(() => null)]);
    }
    await rm(directory, { recursive: true, force: true });
    assert.equal(outcome?.code, 0, stderr.slice(-1500));
  }
});
