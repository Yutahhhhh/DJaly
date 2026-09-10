// SOUND COLOR FX reports its state from ControlObjects, so a processor the audio
// thread still considers disabled looks identical to a working one. Record the
// master bus instead: the filter must actually shape the tone, and selecting a
// different Color FX while the knob sits at its centre must still make a sound.
import test from 'node:test';
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { mkdtemp, writeFile, readFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { createInterface } from 'node:readline';

const delay = ms => new Promise(resolve => setTimeout(resolve, ms));

/** Three separated bands under a gated envelope: the bands expose a filter, the
 *  silent gaps expose anything with a tail. */
function fixture() {
  const rate = 44100, frames = rate * 24;
  const data = Buffer.alloc(44 + frames * 4);
  data.write('RIFF'); data.writeUInt32LE(data.length - 8, 4); data.write('WAVEfmt ', 8);
  data.writeUInt32LE(16, 16); data.writeUInt16LE(1, 20); data.writeUInt16LE(2, 22);
  data.writeUInt32LE(rate, 24); data.writeUInt32LE(rate * 4, 28);
  data.writeUInt16LE(4, 32); data.writeUInt16LE(16, 34); data.write('data', 36); data.writeUInt32LE(frames * 4, 40);
  for (let n = 0; n < frames; n++) {
    const envelope = n % rate < rate * 0.65 ? 1 : 0;
    const value = Math.round(envelope * 2200 * [80, 1000, 8000].reduce((sum, hz) => sum + Math.sin(2 * Math.PI * hz * n / rate), 0));
    data.writeInt16LE(value, 44 + n * 4); data.writeInt16LE(value, 46 + n * 4);
  }
  return data;
}

function analyse(wav) {
  let pcm, rate, bits;
  for (let offset = 12; offset + 8 <= wav.length;) {
    const name = wav.toString('ascii', offset, offset + 4), size = wav.readUInt32LE(offset + 4);
    if (name === 'fmt ') { rate = wav.readUInt32LE(offset + 12); bits = wav.readUInt16LE(offset + 22); }
    if (name === 'data') pcm = wav.subarray(offset + 8, offset + 8 + size);
    offset += 8 + size + size % 2;
  }
  assert.equal(bits, 16);
  assert(pcm?.length > 1000, `Finalized WAV PCM required (${wav.length} bytes)`);
  const width = 8192, bands = [0, 0, 0];
  let minimumRms = Infinity;
  for (let start = Math.floor(rate * 0.2); start + 1024 < pcm.length / 4; start += 1024) {
    let sum = 0;
    for (let n = 0; n < 1024; n++) sum += pcm.readInt16LE((start + n) * 4) ** 2;
    minimumRms = Math.min(minimumRms, Math.sqrt(sum / 1024));
  }
  for (let start = Math.floor(rate * 0.2); start + width < pcm.length / 4; start += width) {
    [80, 1000, 8000].forEach((hz, band) => {
      let real = 0, imaginary = 0;
      for (let n = 0; n < width; n++) {
        const sample = pcm.readInt16LE((start + n) * 4), phase = 2 * Math.PI * hz * n / rate;
        real += sample * Math.cos(phase); imaginary += sample * Math.sin(phase);
      }
      bands[band] = Math.max(bands[band], 2 * Math.hypot(real, imaginary) / width);
    });
  }
  return { bands, minimumRms };
}

test('SOUND COLOR FX shapes real audio, including a switch made at the knob centre', { timeout: 120000 }, async () => {
  const directory = await mkdtemp(path.join(tmpdir(), 'plumdeck-colorfx-audio-'));
  const audioPath = path.join(directory, 'tones.wav');
  await writeFile(audioPath, fixture());
  const output = process.env.PLUMDECK_MIXXX_OUTPUT_DEVICE || 'BlackHole 2ch';
  const binary = process.env.PLUMDECK_TEST_HOST || path.resolve(import.meta.dirname, '../build-upstream/plumdeck-mixxx-engine-host');
  const child = spawn(binary, [], { env: { ...process.env, PLUMDECK_MIXXX_OUTPUT_DEVICE: output, PLUMDECK_MIXXX_RECORDING_DIR: directory } });
  let id = 0, hello, stderr = '';
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
  const until = async predicate => {
    for (let n = 0; n < 200; n++) { const state = await command('state.snapshot'); if (predicate(state)) return state; await delay(25); }
    throw new Error('State timeout');
  };
  const record = async () => {
    await delay(1150); // The next file needs a distinct name from the last one.
    await command('recording.start');
    const state = await until(s => s.recording.active);
    await delay(1500);
    await command('recording.stop');
    await until(s => !s.recording.active && !s.recording.stopping);
    return analyse(await readFile(state.recording.path));
  };

  try {
    hello = await command('session.hello');
    await until(s => s.audio.applied);
    await command('deck.load', { deck: 'A', track: { trackId: 'A', path: audioPath, beatTimesMs: [125, 625, 1125, 1675, 2225, 2825, 3425, 4025, 4675, 5325, 6000, 6675] } });
    await until(s => s.decks.A.track && s.decks.A.status !== 'loading');
    await command('deck.seek', { deck: 'A', positionMs: 0 });
    await command('deck.loop.set', { deck: 'A', startMs: 0, endMs: 16000 });
    await command('deck.loop.enable', { deck: 'A', enabled: true });
    await command('deck.play', { deck: 'A' });

    const flat = await record();
    assert(flat.bands[2] > 100, `the fixture must carry a high band to filter: ${flat.bands[2]}`);

    await command('mixer.colorfx.set', { deck: 'A', effect: 'filter', amount: -0.9 });
    const lowpass = await record();
    assert(lowpass.bands[2] < flat.bands[2] * 0.5, `FILTER towards LPF must cut 8kHz: ${lowpass.bands[2]} vs ${flat.bands[2]}`);

    // Centre the knob, then pick a different Color FX. The processor is loaded
    // while the chain is off, which is where the enable state used to be lost.
    await command('mixer.colorfx.set', { deck: 'A', effect: 'filter', amount: 0 });
    await command('mixer.colorfx.set', { deck: 'A', effect: 'echo', amount: 0.9 });
    const echo = await record();
    assert(echo.minimumRms > Math.max(3, flat.minimumRms * 5),
      `D-ECHO selected at the knob centre must still be audible: ${echo.minimumRms} vs ${flat.minimumRms}`);

    await command('mixer.colorfx.set', { deck: 'A', effect: 'echo', amount: 0 });
    const off = await record();
    assert(off.minimumRms < Math.max(3, flat.minimumRms * 5), `returning to the centre must leave no tail: ${off.minimumRms}`);
  } finally {
    child.stdin.end();
    await Promise.race([exited, delay(1000)]);
    child.kill();
    await rm(directory, { recursive: true, force: true });
  }
});
