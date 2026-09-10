import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { mkdtemp, readFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { createInterface } from 'node:readline';
import test from 'node:test';

const binary = process.env.PLUMDECK_TEST_HOST || path.resolve(import.meta.dirname, '../build-upstream/plumdeck-mixxx-engine-host');
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));

test('recording completion finalizes WAV and rapid start/stop cannot stick', { timeout: 30000 }, async () => {
  const directory = await mkdtemp(path.join(tmpdir(), 'plumdeck-finalize-'));
  const child = spawn(binary, [], { env: { ...process.env, PLUMDECK_MIXXX_OUTPUT_DEVICE: process.env.PLUMDECK_MIXXX_OUTPUT_DEVICE || 'BlackHole 2ch', PLUMDECK_MIXXX_RECORDING_DIR: directory } });
  let hello, nextId = 0, stderr = '';
  const pending = new Map();
  child.stderr.on('data', chunk => { stderr += chunk; });
  createInterface({ input: child.stdout }).on('line', line => {
    const value = JSON.parse(line);
    if (value.kind !== 'event') pending.get(value.id)?.(value);
  });
  function command(op, params = {}) {
    const id = ++nextId;
    const reply = new Promise((resolve, reject) => {
      const timer = setTimeout(() => reject(new Error(`Timeout ${op}: ${stderr.slice(-1200)}`)), 10000);
      pending.set(id, value => { clearTimeout(timer); pending.delete(id); resolve(value); });
    });
    child.stdin.write(JSON.stringify({ id, op, params, ...(hello ? { engineId: hello.engineId, sessionId: hello.sessionId } : {}) }) + '\n');
    return reply.then(value => { assert.notEqual(value.kind, 'error', JSON.stringify(value)); return value.data ?? value; });
  }
  async function until(predicate) {
    for (let n = 0; n < 300; n++) {
      const state = await command('state.snapshot');
      if (predicate(state)) return state;
      await delay(20);
    }
    throw new Error('Recording state did not settle');
  }
  async function assertReadable(recording) {
    assert.equal(recording.active, false);
    assert.equal(recording.stopping, false);
    const wav = await readFile(recording.path); // No retry or finalization delay.
    assert.equal(wav.toString('ascii', 0, 4), 'RIFF');
    assert.equal(wav.readUInt32LE(4) + 8, wav.length, 'RIFF length finalized');
    let dataSize;
    for (let offset = 12; offset + 8 <= wav.length;) {
      const tag = wav.toString('ascii', offset, offset + 4), size = wav.readUInt32LE(offset + 4);
      if (tag === 'data') dataSize = size;
      offset += 8 + size + size % 2;
    }
    assert.equal(typeof dataSize, 'number', 'WAV data chunk finalized');
    assert(dataSize <= wav.length - 44);
  }
  try {
    hello = await command('session.hello');
    await until(state => state.audio.applied);
    await command('recording.start');
    const started = await until(state => state.recording.active);
    await delay(350);
    const stopping = await command('recording.stop');
    assert(stopping.active && stopping.stopping, 'Stop acknowledges finalization still in progress');
    assert.equal(stopping.path, started.recording.path);
    const ignoredRestart = await command('recording.start');
    assert.equal(ignoredRestart.path, stopping.path, 'Start cannot replace pending recording');
    const finished = await until(state => !state.recording.active && !state.recording.stopping);
    assert.equal(finished.recording.path, stopping.path);
    assert.equal(finished.recording.elapsedMs, stopping.elapsedMs, 'Elapsed freezes at stop request');
    assert.equal(finished.recording.sampleRateHz, 44100, 'Recorder exposes its real sample rate');
    assert(finished.recording.frameCount > 0, 'Recorder exposes frames written by the recording callback');
    assert.equal(finished.recording.elapsedMs, Math.floor(finished.recording.frameCount * 1000 / finished.recording.sampleRateHz), 'Elapsed is derived from recorder frames');
    assert.equal(finished.recording.timelineQuality, 'recording_frame_clock');
    assert(Array.isArray(finished.recording.timeline), 'Recording timeline is part of the final state');
    await assertReadable(finished.recording);
    await delay(1150); // Existing filename collision cooldown, after readability check.
    const starting = command('recording.start');
    const immediateStop = command('recording.stop');
    await starting;
    await immediateStop;
    const rapid = await until(state => !state.recording.active && !state.recording.stopping);
    assert.notEqual(rapid.recording.path, finished.recording.path);
    await assertReadable(rapid.recording);
  } finally {
    child.stdin.end();
    const timer = setTimeout(() => child.kill(), 5000); timer.unref();
  }
});
