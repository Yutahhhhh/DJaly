import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { mkdtemp, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { createInterface } from 'node:readline';
import test from 'node:test';

const binary = process.env.PLUMDECK_TEST_HOST || path.resolve(import.meta.dirname, '../build-upstream/plumdeck-mixxx-engine-host');
const delay = milliseconds => new Promise(resolve => setTimeout(resolve, milliseconds));

function wav(seconds, sampleRate = 44100) {
  const frameCount = seconds * sampleRate;
  const data = Buffer.alloc(44 + frameCount * 4);
  data.write('RIFF'); data.writeUInt32LE(data.length - 8, 4); data.write('WAVEfmt ', 8);
  data.writeUInt32LE(16, 16); data.writeUInt16LE(1, 20); data.writeUInt16LE(2, 22);
  data.writeUInt32LE(sampleRate, 24); data.writeUInt32LE(sampleRate * 4, 28);
  data.writeUInt16LE(4, 32); data.writeUInt16LE(16, 34); data.write('data', 36);
  data.writeUInt32LE(frameCount * 4, 40);
  return data;
}

test('native variable beat maps survive load and live replacement with strict validation', { timeout: 30000 }, async () => {
  const directory = await mkdtemp(path.join(tmpdir(), 'plumdeck-variable-grid-'));
  const fixture = path.join(directory, 'variable.wav');
  await writeFile(fixture, wav(8));
  const child = spawn(binary, [], { env: { ...process.env, PLUMDECK_MIXXX_TIMING_TRACE: '1', PLUMDECK_MIXXX_OUTPUT_DEVICE: process.env.PLUMDECK_MIXXX_OUTPUT_DEVICE || 'BlackHole 2ch' } });
  let stderr = '', nextId = 0, hello;
  const pending = new Map();
  child.stderr.on('data', chunk => { stderr += chunk; });
  const exited = new Promise(resolve => child.once('exit', (code, signal) => resolve({ code, signal })));
  createInterface({ input: child.stdout }).on('line', line => {
    const message = JSON.parse(line);
    if (message.kind !== 'event') pending.get(message.id)?.(message);
  });
  async function command(op, params = {}, errorCode) {
    const id = ++nextId;
    const reply = new Promise((resolve, reject) => {
      const timer = setTimeout(() => reject(new Error(`Timeout: ${op}; ${stderr.slice(-1200)}`)), 10000);
      pending.set(id, message => { clearTimeout(timer); pending.delete(id); resolve(message); });
    });
    child.stdin.write(JSON.stringify({ id, op, params, ...(hello ? { engineId: hello.engineId, sessionId: hello.sessionId } : {}) }) + '\n');
    const message = await reply;
    if (errorCode) assert.equal(message.error?.code, errorCode, JSON.stringify(message));
    else assert.notEqual(message.kind, 'error', JSON.stringify(message));
    return message;
  }
  async function until(predicate) {
    for (let attempt = 0; attempt < 120; attempt++) {
      const state = (await command('state.snapshot')).data;
      if (predicate(state)) return state;
      await delay(30);
    }
    throw new Error('Snapshot condition did not become true');
  }
  try {
    hello = await command('session.hello');
    await until(state => state.audio.applied);

    // Constant analysis data and tempo must survive backspins and side nudges.
    await command('deck.load', {deck:'A', track:{trackId:'constant', path:fixture, bpm:120, beatgridOffsetMs:125}});
    await until(state=>state.decks.A.track?.beatgridApplied);
    await command('deck.seek',{deck:'A',positionMs:4000});
    await command('deck.play',{deck:'A'});
    await until(state=>state.decks.A.effectiveBpm===120);
    await command('deck.timing.trace',{deck:'A'});
    await command('deck.pitchbend',{deck:'A',amount:-.5});
    await delay(100);
    const bent=(await command('deck.timing.trace',{deck:'A'})).data.rows;
    assert(bent.some(row=>row.speed < .9 && row.speed > .1),'Bend must change actual audio speed');
    await delay(300);
    const restored=(await command('deck.timing.trace',{deck:'A'})).data.rows.slice(-5);
    assert(restored.length>0 && restored.every(row=>Math.abs(row.speed-1)<.02),'Native watchdog must restore speed without a client release');
    for (const amount of [-.5,.5,-.75]) {
      await command('deck.pitchbend',{deck:'A',amount,trackId:'constant'});
      await delay(40);
      const deck=(await command('state.snapshot')).data.decks.A;
      assert.equal(deck.rate,1,'Pitch bend must not write the tempo slider');
      assert.equal(deck.effectiveBpm,120,'Pitch bend must not change musical BPM');
    }
    await command('deck.scratch',{deck:'A',phase:'begin',positionMs:0,gestureId:'backspin'});
    for(let i=1;i<=20;i++) {
      await command('deck.scratch',{deck:'A',phase:'move',positionMs:-i*40,gestureId:'backspin'});
      await delay(20);
      const deck=(await command('state.snapshot')).data.decks.A;
      assert.equal(deck.rate,1);
      assert.equal(deck.effectiveBpm,120);
      assert.equal(deck.track.bpm,120);
      assert.equal(deck.track.beatgridOffsetMs,125);
      assert.equal(deck.track.nativeBeatgrid.constantTempo,true);
    }
    await command('deck.scratch',{deck:'A',phase:'end',positionMs:-800,gestureId:'backspin'});
    await delay(300);
    assert.equal((await command('state.snapshot')).data.decks.A.rate,1);
    await command('deck.pitchbend',{deck:'A',amount:1},'invalid_params');
    await command('deck.pitchbend',{deck:'A',amount:.1,trackId:'stale'},'invalid_params');

    const beatTimesMs = [125, 625, 1125, 1675, 2225, 2825, 3425, 4025, 4675, 5325];
    const beatNumbers = [1, 2, 3, 4, 1, 2, 3, 4, 1, 2];
    await command('deck.load', { deck: 'A', track: { trackId: 'variable-A', path: fixture, beatTimesMs, beatNumbers, beatsPerBar: 4 } });
    const loaded = await until(state => state.decks.A.track?.beatgridApplied);
    assert.deepEqual(loaded.decks.A.track.beatTimesMs, beatTimesMs);
    assert.deepEqual(loaded.decks.A.track.beatNumbers, beatNumbers);
    assert.equal(Object.hasOwn(loaded.decks.A.track, 'beatgridOffsetMs'), false, 'missing offsets must not become zero');
    assert.equal(loaded.decks.A.track.nativeBeatgrid.constantTempo, false);
    assert(loaded.decks.A.track.nativeBeatgrid.markerCount > 0);
    assert(Math.abs(loaded.decks.A.track.nativeBeatgrid.lastMarkerMs - beatTimesMs.at(-1)) < 0.03);

    await command('deck.tempo.set', { deck: 'A', rate: 1.1 });
    await command('deck.keylock.set', { deck: 'A', enabled: true });
    await command('deck.sync.set', { deck: 'A', enabled: true });
    await command('deck.play', { deck: 'A' });
    const before = await until(state => state.decks.A.status === 'playing' && state.decks.A.positionMs > 100);
    const replacement = [200, 700, 1230, 1760, 2320, 2880, 3470, 4060, 4680, 5300];
    const applied = (await command('deck.beatgrid.set', { deck: 'A', trackId: 'variable-A', beatTimesMs: replacement, beatsPerBar: 4 })).data;
    assert.deepEqual(applied.track.beatTimesMs, replacement);
    assert.equal(applied.track.bpm, null, 'a missing variable-grid BPM must not retain stale metadata');
    assert.equal(applied.track.nativeBeatgrid.constantTempo, false);
    assert(applied.track.nativeBeatgrid.markerCount > 0);
    assert.equal(applied.keylock, true); assert.equal(applied.syncEnabled, true);
    const after = await until(state => state.decks.A.positionMs > before.decks.A.positionMs + 80);
    assert.equal(after.decks.A.status, 'playing');
    assert.equal(after.decks.A.track.trackId, 'variable-A');

    // 保存グリッドの末尾拍はデコード実尺を超えることがある（デコーダが
    // MP3/AAC の前後無音を落とすため）。届かない拍だけ捨てて適用する。
    const overshoot = (await command('deck.beatgrid.set', { deck: 'A', trackId: 'variable-A', beatTimesMs: [...replacement, 8000, 8200], beatsPerBar: 4 })).data;
    assert.deepEqual(overshoot.track.beatTimesMs, replacement, 'beats behind the decoded end are dropped, not fatal');
    assert.equal(overshoot.track.beatgridApplied, true);

    // Validate the entire input before trimming, including unreachable numbers.
    for (const numbers of [[1, 2], [1, 2, 0], [1, 2, 3, 4]]) {
      await command('deck.beatgrid.set', { deck: 'A', trackId: 'variable-A', beatTimesMs: [100, 600, 8200], beatNumbers: numbers }, 'invalid_params');
    }
    const trimmed = (await command('deck.beatgrid.set', { deck: 'A', trackId: 'variable-A', beatTimesMs: [100, 600, 8200], beatNumbers: [3, 4, 1] })).data;
    assert.deepEqual(trimmed.track.beatTimesMs, [100, 600]);
    assert.deepEqual(trimmed.track.beatNumbers, [3, 4]);

    const base = { deck: 'A', trackId: 'variable-A', beatTimesMs: replacement };
    for (const change of [
      { beatTimesMs: 'bad' }, { beatTimesMs: [100] }, { beatTimesMs: [100, 100] },
      { beatTimesMs: [100, 90] }, { beatTimesMs: [-1, 100] }, { beatTimesMs: [100, 8000] },
      { beatTimesMs: [100, null] }, { beatNumbers: [1] },
      { beatNumbers: replacement.map(() => 0) }, { beatNumbers: replacement.map(() => 17) },
      { beatNumbers: replacement.map(() => 1.5) }, { beatNumbers: replacement.map(() => 5), beatsPerBar: 4 },
      { beatsPerBar: 0 }, { bpm: 301 }, { firstBeatMs: -1 },
    ]) await command('deck.beatgrid.set', { ...base, ...change }, 'invalid_params');

    await command('deck.load', { deck: 'B', track: { trackId: 'no-grid', path: fixture } });
    const noGrid = await until(state => state.decks.B.track);
    assert.equal(noGrid.decks.B.track.beatgridApplied, false);
    assert.equal(Object.hasOwn(noGrid.decks.B.track, 'beatgridOffsetMs'), false);

    await command('deck.load', { deck: 'C', track: { trackId: 'bad-duration', path: fixture, beatTimesMs: [100, 9000] } });
    const failed = await until(state => state.decks.C.status === 'error');
    assert.match(failed.decks.C.lastError, /duration/);

    // Catalog duration exceeds decoded duration; keep in-range markers and
    // their original beat numbers, including on a deck recovering from error.
    await command('deck.load', { deck: 'C', track: {
      trackId: 'trimmed-tail', path: fixture, durationMs: 8500,
      beatTimesMs: [125, 625, 7999, 8000, 8250], beatNumbers: [3, 4, 1, 2, 3], beatsPerBar: 4,
    } });
    const recovered = await until(state => state.decks.C.track?.trackId === 'trimmed-tail' && state.decks.C.track.beatgridApplied);
    assert.equal(recovered.decks.C.status, 'ready');
    assert.equal(recovered.decks.C.track.durationMs, 8000);
    assert.deepEqual(recovered.decks.C.track.beatTimesMs, [125, 625, 7999]);
    assert.deepEqual(recovered.decks.C.track.beatNumbers, [3, 4, 1]);
    assert(Math.abs(recovered.decks.C.track.nativeBeatgrid.lastMarkerMs - 7999) < 0.03);

    for (const track of [
      { trackId: 'bad-shape', path: fixture, beatTimesMs: [100] },
      { trackId: 'bad-order', path: fixture, beatTimesMs: [200, 100] },
      { trackId: 'bad-numbers', path: fixture, beatTimesMs: [100, 200], beatNumbers: [1] },
      { trackId: 'above-default-meter', path: fixture, beatTimesMs: [100, 200], beatNumbers: [1, 5] },
      { trackId: 'orphan-numbers', path: fixture, beatNumbers: [1, 2] },
    ]) await command('deck.load', { deck: 'D', track }, 'invalid_params');
  } finally {
    child.stdin.end();
    const outcome = await Promise.race([exited, delay(3000).then(() => null)]);
    if (!outcome) child.kill('SIGTERM');
    await rm(directory, { recursive: true, force: true });
    assert.equal(outcome?.code, 0, stderr.slice(-1600));
  }
});
