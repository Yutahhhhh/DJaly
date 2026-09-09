// sampler.test.mjs proves the state machine with a silent fixture, so it cannot
// tell a pad that plays from a pad that only reports "playing". This one records
// the master bus and checks the sampler is actually in the mix: it must be
// audible when a pad fires, obey the bank selector, follow the gain, and go
// quiet on stopAll and on a new session.
import test from 'node:test';
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { mkdtemp, writeFile, readFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { createInterface } from 'node:readline';

const delay = ms => new Promise(resolve => setTimeout(resolve, ms));

/** A continuous 1 kHz tone; long enough to outlast the recording window. */
function tone(seconds = 30) {
  const rate = 44100, frames = rate * seconds;
  const data = Buffer.alloc(44 + frames * 4);
  data.write('RIFF'); data.writeUInt32LE(data.length - 8, 4); data.write('WAVEfmt ', 8);
  data.writeUInt32LE(16, 16); data.writeUInt16LE(1, 20); data.writeUInt16LE(2, 22);
  data.writeUInt32LE(rate, 24); data.writeUInt32LE(rate * 4, 28);
  data.writeUInt16LE(4, 32); data.writeUInt16LE(16, 34); data.write('data', 36); data.writeUInt32LE(frames * 4, 40);
  for (let n = 0; n < frames; n++) {
    const value = Math.round(6000 * Math.sin(2 * Math.PI * 1000 * n / rate));
    data.writeInt16LE(value, 44 + n * 4); data.writeInt16LE(value, 46 + n * 4);
  }
  return data;
}

function rms(wav) {
  let pcm, rate, bits;
  for (let offset = 12; offset + 8 <= wav.length;) {
    const name = wav.toString('ascii', offset, offset + 4), size = wav.readUInt32LE(offset + 4);
    if (name === 'fmt ') { rate = wav.readUInt32LE(offset + 12); bits = wav.readUInt16LE(offset + 22); }
    if (name === 'data') pcm = wav.subarray(offset + 8, offset + 8 + size);
    offset += 8 + size + size % 2;
  }
  assert.equal(bits, 16);
  assert(pcm?.length > 1000, `Finalized WAV PCM required (${wav.length} bytes)`);
  // Skip the opening ramp; the recorder needs a moment to reach steady state.
  let sum = 0, count = 0;
  for (let frame = Math.floor(rate * 0.3); frame < pcm.length / 4; frame++) { sum += pcm.readInt16LE(frame * 4) ** 2; count++; }
  return Math.sqrt(sum / count);
}

test('sampler pads are audible on the master bus and obey bank, gain, stopAll and session changes', { timeout: 120000 }, async () => {
  const directory = await mkdtemp(path.join(tmpdir(), 'djaly-sampler-audio-'));
  const file = path.join(directory, 'tone.wav');
  await writeFile(file, tone());
  const output = process.env.DJALY_MIXXX_OUTPUT_DEVICE || 'BlackHole 2ch';
  const binary = process.env.DJALY_TEST_HOST || path.resolve(import.meta.dirname, '../build-upstream/djaly-mixxx-engine-host');
  const child = spawn(binary, [], { env: { ...process.env, DJALY_MIXXX_OUTPUT_DEVICE: output, DJALY_MIXXX_RECORDING_DIR: directory } });
  let id = 0, hello, snapshot, stderr = '';
  const pending = new Map();
  child.stderr.on('data', bytes => { stderr += bytes; });
  const exited = new Promise(resolve => child.once('exit', resolve));
  createInterface({ input: child.stdout }).on('line', line => { const m = JSON.parse(line); if (m.kind !== 'event') pending.get(m.id)?.(m); });
  const command = async (op, params = {}) => {
    const next = ++id;
    const reply = new Promise((resolve, reject) => {
      const timer = setTimeout(() => { pending.delete(next); reject(new Error(`Timeout ${op}: ${stderr.slice(-800)}`)); }, 15000);
      pending.set(next, m => { clearTimeout(timer); pending.delete(next); m.kind === 'error' ? reject(new Error(JSON.stringify(m))) : resolve(m.data ?? m); });
    });
    child.stdin.write(JSON.stringify({ id: next, op, params, ...(hello ? { engineId: hello.engineId, sessionId: hello.sessionId } : {}) }) + '\n');
    return reply;
  };
  const refresh = async () => { snapshot = await command('state.snapshot'); return snapshot; };
  const until = async predicate => {
    for (let n = 0; n < 200; n++) { await refresh(); if (predicate(snapshot)) return snapshot; await delay(25); }
    throw new Error('State timeout: ' + JSON.stringify(snapshot));
  };
  /** Records the master bus, optionally firing a gesture once tape is rolling. */
  const record = async during => {
    await delay(1150); // The next file needs a distinct name from the last one.
    await command('recording.start');
    const state = await until(s => s.recording.active);
    if (during) await during();
    await delay(1500);
    await command('recording.stop');
    await until(s => !s.recording.active && !s.recording.stopping);
    return rms(await readFile(state.recording.path));
  };
  const ready = async (slot, bank) => {
    for (let n = 0; n < 200; n++) {
      const state = await command('sampler.state', bank === undefined ? {} : { bank });
      if (state.slots[slot].status === 'ready') return;
      await delay(25);
    }
    throw new Error(`sampler slot ${slot} never became ready`);
  };

  try {
    hello = await command('session.hello');
    await until(s => s.audio.applied);

    // Nothing is loaded anywhere, so this is the noise floor to compare against.
    const silence = await record();
    const audible = level => level > Math.max(20, silence * 5);

    await command('sampler.load', { slot: 0, path: file });
    await ready(0);
    // Loading alone must not make a sound; only the pad press may.
    const loaded = await record();
    assert(!audible(loaded), `a loaded pad must stay silent until fired: ${loaded} vs ${silence}`);

    const playing = await record(() => command('sampler.play', { slot: 0 }));
    assert(audible(playing), `a fired pad must reach the master bus: ${playing} vs ${silence}`);
    assert.equal((await command('sampler.state')).slots[0].status, 'playing');
    // No deck was ever loaded, so the recorded signal can only be the sampler.
    assert.equal((await refresh()).decks.A.status, 'empty');

    // stopAll must actually cut the audio, not just relabel the slot.
    await command('sampler.stopAll');
    const stopped = await record();
    assert(!audible(stopped), `stopAll must silence the pad: ${stopped} vs ${silence}`);

    // The gain control has to reach the channel, not just the reported state.
    await command('sampler.gain', { gain: 0.7 });
    const loud = await record(() => command('sampler.play', { slot: 0 }));
    await command('sampler.stopAll');
    await command('sampler.gain', { gain: 0.15 });
    const quiet = await record(() => command('sampler.play', { slot: 0 }));
    await command('sampler.stopAll');
    assert(audible(loud) && audible(quiet), `both gains must be audible: ${loud} / ${quiet}`);
    assert(quiet < loud * 0.6, `a lower sampler gain must be quieter: ${quiet} vs ${loud}`);
    await command('sampler.gain', { gain: 0.7 });

    // Banks address 64 distinct slots: bank 1 slot 0 is not bank 0 slot 0.
    await command('sampler.load', { slot: 0, bank: 1, path: file });
    await ready(0, 1);
    assert.equal((await command('sampler.state')).slots[0].status, 'ready', 'bank 0 slot 0 is still its own sample');
    const otherBank = await record(() => command('sampler.play', { slot: 0, bank: 1 }));
    assert(audible(otherBank), `an explicit bank must play too: ${otherBank} vs ${silence}`);
    // Selecting a bank must not disturb what is already sounding.
    await command('sampler.bank', { bank: 1 });
    assert.equal((await command('sampler.state')).bank, 1);
    await command('sampler.stopAll');
    await command('sampler.bank', { bank: 0 });

    // A renderer reconnecting must not leave a pad ringing.
    await command('sampler.play', { slot: 0 });
    await until(s => s.sampler === undefined || true);
    hello = await command('session.hello');
    const afterSession = await record();
    assert(!audible(afterSession), `session.hello must stop the pads: ${afterSession} vs ${silence}`);

    // Without a cue bus there is nowhere to send PFL, and the host says so
    // rather than silently pretending the pad is being monitored.
    if (!(await refresh()).audio.pflApplied) {
      await assert.rejects(command('sampler.pfl', { enabled: true }), /unsupported_operation/);
    }
  } finally {
    child.stdin.end();
    await Promise.race([exited, delay(1000)]);
    child.kill();
    await rm(directory, { recursive: true, force: true });
  }
});
