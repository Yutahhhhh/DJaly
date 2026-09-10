// エンジン起動直後の最初のエフェクト操作が実際に音になることを守る。
// 詳細は test 本体のコメントを参照。
import assert from 'node:assert/strict';
import test from 'node:test';
import { spawn } from 'node:child_process';
import { mkdtemp, writeFile, readFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { createInterface } from 'node:readline';

const binary = process.env.PLUMDECK_TEST_HOST || path.resolve(import.meta.dirname, '../build-upstream/plumdeck-mixxx-engine-host');
const delay = ms => new Promise(r => setTimeout(r, ms));
function fixture() {
  const rate = 44100, frames = rate * 24;
  const data = Buffer.alloc(44 + frames * 4);
  data.write('RIFF'); data.writeUInt32LE(data.length - 8, 4); data.write('WAVEfmt ', 8);
  data.writeUInt32LE(16, 16); data.writeUInt16LE(1, 20); data.writeUInt16LE(2, 22);
  data.writeUInt32LE(rate, 24); data.writeUInt32LE(rate * 4, 28);
  data.writeUInt16LE(4, 32); data.writeUInt16LE(16, 34); data.write('data', 36); data.writeUInt32LE(frames * 4, 40);
  for (let n = 0; n < frames; n++) {
    // Separated low, middle and high bands; amplitude envelope exposes FX tails.
    const envelope = n % rate < rate * 0.65 ? 1 : 0;
    const value = Math.round(envelope * 2200 * [80, 1000, 8000].reduce((sum, hz) => sum + Math.sin(2 * Math.PI * hz * n / rate), 0));
    data.writeInt16LE(value, 44 + n * 4); data.writeInt16LE(value, 46 + n * 4);
  }
  return data;
}
function amplitudes(wav) {
  let pcm, rate, bits;
  for (let offset = 12; offset + 8 <= wav.length;) {
    const name = wav.toString('ascii', offset, offset + 4), size = wav.readUInt32LE(offset + 4);
    if (name === 'fmt ') { rate = wav.readUInt32LE(offset + 12); bits = wav.readUInt16LE(offset + 22); }
    if (name === 'data') pcm = wav.subarray(offset + 8, offset + 8 + size);
    offset += 8 + size + size % 2;
  }
  assert.equal(bits, 16); assert(pcm?.length > 1000, `Finalized WAV PCM required (${wav.length} bytes; header ${wav.subarray(0, 100).toString('hex')})`);
  const width = 8192, result = [0, 0, 0];
  result.minimumRms = Infinity;
  for (let start = Math.floor(rate * 0.2); start + 1024 < pcm.length / 4; start += 1024) {
    let sum = 0;
    for (let n = 0; n < 1024; n++) sum += pcm.readInt16LE((start + n) * 4) ** 2;
    result.minimumRms = Math.min(result.minimumRms, Math.sqrt(sum / 1024));
  }
  // Find the strongest sustained tone window, ignoring recording startup ramps.
  for (let start = Math.floor(rate * 0.2); start + width < pcm.length / 4; start += width) {
    [80, 1000, 8000].forEach((hz, band) => {
      let real = 0, imaginary = 0;
      for (let n = 0; n < width; n++) {
        const sample = pcm.readInt16LE((start + n) * 4), phase = 2 * Math.PI * hz * n / rate;
        real += sample * Math.cos(phase); imaginary += sample * Math.sin(phase);
      }
      result[band] = Math.max(result[band], 2 * Math.hypot(real, imaginary) / width);
    });
  }
  return result;
}


/**
 * エンジン起動後の「最初の 1 回」の mixer.fx.set が無音になっていた。空のチェーンへ
 * ロードしてから同じ呼び出しで有効化すると、プロセッサがまだ差し変わっておらず
 * 音に出ない。最初に押したパッドだけ効かない、という形で表に出ていた。
 */
/**
 * 保存先はプロセスを立て直さずに変えられなければならない。RecordingManager は
 * 録音のたびに設定を読み直すので、op で書き換えれば次の録音から効く。
 */
test('the recording directory can be changed without restarting the host', { timeout: 90000 }, async () => {
  const directory = await mkdtemp(path.join(tmpdir(), 'plumdeck-recdir-'));
  const child = spawn(binary, [], { env: { ...process.env, PLUMDECK_MIXXX_OUTPUT_DEVICE: process.env.PLUMDECK_MIXXX_OUTPUT_DEVICE || 'BlackHole 2ch', PLUMDECK_MIXXX_RECORDING_DIR: directory } });
  let stderr = '', nextId = 0, hello;
  const pending = new Map();
  child.stderr.on('data', chunk => { stderr += chunk; });
  createInterface({ input: child.stdout }).on('line', line => { const value = JSON.parse(line); if (value.kind !== 'event') pending.get(value.id)?.(value); });
  async function command(op, params = {}) {
    const id = ++nextId;
    const reply = new Promise((resolve, reject) => {
      const timer = setTimeout(() => reject(new Error(`Timeout ${op}: ${stderr.slice(-600)}`)), 10000);
      pending.set(id, value => { clearTimeout(timer); pending.delete(id); resolve(value); });
    });
    child.stdin.write(JSON.stringify({ id, op, params, ...(hello ? { engineId: hello.engineId, sessionId: hello.sessionId } : {}) }) + '\n');
    return reply;
  }
  async function until(predicate) {
    for (let n = 0; n < 200; n++) { const reply = await command('state.snapshot'); const state = reply.data ?? reply; if (predicate(state)) return state; await delay(25); }
    throw new Error('timeout');
  }
  async function recordOnce() {
    await command('recording.start');
    const state = await until(s => s.recording.active);
    await delay(500);
    await command('recording.stop');
    await delay(1200); // ファイル名を一意にするためのクールダウン
    return state.recording.path;
  }
  try {
    const greeting = await command('session.hello'); hello = greeting.data ?? greeting;
    await until(state => state.audio.applied);

    await command('recording.directory.set', { directory: path.join(directory, 'first') });
    const first = await recordOnce();
    assert.match(first, /\/first\//, `最初の保存先: ${first}`);

    // ここでプロセスは立て直さない。
    await command('recording.directory.set', { directory: path.join(directory, 'second') });
    const second = await recordOnce();
    assert.match(second, /\/second\//, `再起動なしで切り替わること: ${second}`);

    const relative = await command('recording.directory.set', { directory: 'not-absolute' });
    assert.equal(relative.error?.code, 'invalid_params', '相対パスは拒否する');
  } finally { child.kill(); }
});

test('the first FX command after startup is already audible', { timeout: 90000 }, async () => {
  const directory = await mkdtemp(path.join(tmpdir(), 'plumdeck-fxprobe-'));
  const audioPath = path.join(directory, 'tones.wav');
  await writeFile(audioPath, fixture());
  const child = spawn(binary, [], { env: { ...process.env, PLUMDECK_MIXXX_OUTPUT_DEVICE: process.env.PLUMDECK_MIXXX_OUTPUT_DEVICE || 'BlackHole 2ch', PLUMDECK_MIXXX_RECORDING_DIR: directory } });
  let stderr = '', nextId = 0, hello;
  const pending = new Map();
  child.stderr.on('data', c => { stderr += c; });
  createInterface({ input: child.stdout }).on('line', line => { const v = JSON.parse(line); if (v.kind !== 'event') pending.get(v.id)?.(v); });
  async function command(op, params = {}) {
    const id = ++nextId;
    const reply = new Promise((resolve, reject) => {
      const timer = setTimeout(() => reject(new Error(`Timeout ${op}: ${stderr.slice(-800)}`)), 10000);
      pending.set(id, v => { clearTimeout(timer); pending.delete(id); resolve(v); });
    });
    child.stdin.write(JSON.stringify({ id, op, params, ...(hello ? { engineId: hello.engineId, sessionId: hello.sessionId } : {}) }) + '\n');
    const v = await reply;
    if (v.kind === 'error') throw new Error(`${op}: ${JSON.stringify(v.error)}`);
    return v.data || v;
  }
  async function until(p) { let s; for (let n = 0; n < 200; n++) { s = await command('state.snapshot'); if (p(s)) return s; await delay(25); } throw new Error('timeout'); }
  async function record() {
    // Cooldown starts when the previous file has finished closing.
    await delay(1150);
    await command('recording.start');
    const state = await until(s => s.recording.active);
    await delay(1500);
    await command('recording.stop');
    const finished = await until(s => !s.recording.active && !s.recording.stopping);
    const observed = finished.recording.timeline.find(segment => segment.deck === 'A');
    assert(observed, `audible deck must be present in recording timeline: ${JSON.stringify(finished.recording)}`);
    assert.equal(observed.trackId, 42);
    assert(observed.startFrame >= 0 && observed.endFrame > observed.startFrame && observed.endFrame <= finished.recording.frameCount);
    return readFile(state.recording.path);
  }

    hello = await command('session.hello');
    await until(s => s.audio.applied);
    await command('deck.load', { deck: 'A', track: { trackId: 'A', localTrackId: 42, title: 'Timeline fixture', artist: 'plumdeck', path: audioPath, beatTimesMs: [125, 625, 1125, 1675, 2225, 2825, 3425, 4025, 4675, 5325, 6000, 6675] } });
    await until(s => s.decks.A.track && s.decks.A.status !== 'loading');
    await command('deck.seek', { deck: 'A', positionMs: 0 });
    await command('deck.loop.set', { deck: 'A', startMs: 0, endMs: 16000 });
    await command('deck.loop.enable', { deck: 'A', enabled: true });
    await command('deck.play', { deck: 'A' });
  try {
    const flat = amplitudes(await record());
    // 起動してから一度も FX を触っていない状態での最初の一撃。
    await command('mixer.fx.set', { deck: 'A', effect: 'echo', enabled: true, mix: 0.5, depth: 1 });
    const wet = amplitudes(await record());
    assert(wet.minimumRms > Math.max(3, flat.minimumRms * 5),
      `first FX press must produce a PCM tail: ${wet.minimumRms} vs ${flat.minimumRms}`);
    await command('mixer.fx.set', { deck: 'A', effect: 'echo', enabled: false, mix: 0.5, depth: 1 });
  } finally { child.kill(); }
});
