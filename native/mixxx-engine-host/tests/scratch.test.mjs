import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { createInterface } from 'node:readline';
import { mkdtemp, writeFile, readFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import test from 'node:test';

const binary = process.env.DJALY_TEST_HOST || path.resolve(import.meta.dirname, '../build-upstream/djaly-mixxx-engine-host');
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));

function pcmWindow(wave, fromMs, toMs) {
  let format, data;
  for (let offset = 12; offset + 8 <= wave.length;) {
    const length = wave.readUInt32LE(offset + 4);
    if (wave.toString('ascii', offset, offset + 4) === 'fmt ') format = wave.subarray(offset + 8, offset + 8 + length);
    if (wave.toString('ascii', offset, offset + 4) === 'data') data = wave.subarray(offset + 8, offset + 8 + length);
    offset += 8 + length + (length & 1);
  }
  assert(format && data, 'Recorded WAV has fmt/data chunks');
  assert.equal(format.readUInt16LE(0), 1, 'PCM WAV');
  assert.equal(format.readUInt16LE(14), 16, '16-bit PCM');
  const rate = format.readUInt32LE(4), channels = format.readUInt16LE(2);
  const from = Math.floor(fromMs * rate / 1000), to = Math.floor(toMs * rate / 1000);
  assert(to * channels * 2 <= data.length, `Recorded PCM contains the complete measured window: requested ${toMs}ms, have ${data.length / (channels * 2) / rate * 1000}ms`);
  let sum = 0, crossings = 0, previous = 0;
  for (let frame = from; frame < to; frame++) {
    const value = data.readInt16LE(frame * channels * 2);
    sum += value * value;
    if (previous < 0 && value >= 0) crossings++;
    previous = value;
  }
  return { rms: Math.sqrt(sum / (to - from)), frequencyHz: crossings * rate / (to - from) };
}

test('native waveform scratch: paused/playing motion PCM, hold/release, gesture races and watchdog', { timeout: 45000 }, async () => {
  const directory = await mkdtemp(path.join(tmpdir(), 'djaly-native-scratch-'));
  const fixture = path.join(directory, 'mono-48000.wav');
  // A mono source at 48 kHz deliberately differs from the stereo 44.1 kHz
  // engine. Scratch positions must still use SOURCE frames * two.
  const rate = 48000, frames = rate * 30;
  const wave = Buffer.alloc(44 + frames * 2);
  wave.write('RIFF'); wave.writeUInt32LE(wave.length - 8, 4); wave.write('WAVEfmt ', 8);
  wave.writeUInt32LE(16, 16); wave.writeUInt16LE(1, 20); wave.writeUInt16LE(1, 22);
  wave.writeUInt32LE(rate, 24); wave.writeUInt32LE(rate * 2, 28);
  wave.writeUInt16LE(2, 32); wave.writeUInt16LE(16, 34); wave.write('data', 36); wave.writeUInt32LE(frames * 2, 40);
  for (let i = 0; i < frames; i++) wave.writeInt16LE(Math.round(4000 * Math.sin(2 * Math.PI * 440 * i / rate)), 44 + i * 2);
  await writeFile(fixture, wave);
  const child = spawn(binary, [], { env: { ...process.env, DJALY_MIXXX_TIMING_TRACE: '1', DJALY_MIXXX_OUTPUT_DEVICE: process.env.DJALY_MIXXX_OUTPUT_DEVICE || 'BlackHole 2ch', DJALY_MIXXX_RECORDING_DIR: directory } });
  let stderr = '', id = 0, hello, observeTelemetry = false;
  const telemetry = { fullStates: 0, positionEvents: 0, positionBytes: 0, maxPositionBytes: 0, batchedEvents: 0 };
  const observedBpms = new Set();
  const pending = new Map();
  child.stderr.on('data', data => { stderr = (stderr + data).slice(-12000); });
  const exited = new Promise(resolve => child.once('exit', (code, signal) => resolve({ code, signal })));
  createInterface({ input: child.stdout }).on('line', line => {
    const message = JSON.parse(line);
    if (observeTelemetry && message.event === 'deck.state') telemetry.fullStates++;
    if (observeTelemetry && message.event === 'deck.position') {
      telemetry.positionEvents++;
      telemetry.positionBytes += line.length;
      telemetry.maxPositionBytes = Math.max(telemetry.maxPositionBytes, line.length);
      if (message.data.decks.A && message.data.decks.B) telemetry.batchedEvents++;
      const bpm = message.data.decks.A?.effectiveBpm;
      if (typeof bpm === 'number') observedBpms.add(bpm.toFixed(2));
    }
    if (message.kind !== 'event') pending.get(message.id)?.(message);
  });
  async function command(op, params = {}, errorCode) {
    const current = ++id;
    const reply = new Promise((resolve, reject) => {
      const timer = setTimeout(() => { pending.delete(current); reject(new Error(`Timeout: ${op}; ${stderr}`)); }, 5000);
      pending.set(current, message => { clearTimeout(timer); pending.delete(current); resolve(message); });
    });
    child.stdin.write(JSON.stringify({ id: current, op, params, ...(hello ? { engineId: hello.engineId, sessionId: hello.sessionId } : {}) }) + '\n');
    const message = await reply;
    if (errorCode) assert.equal(message.error?.code, errorCode, JSON.stringify(message));
    else assert.notEqual(message.kind, 'error', JSON.stringify(message));
    return message.data ?? message;
  }
  const snapshot = () => command('state.snapshot');
  const scratch = (phase, positionMs, gestureId = 'main') => command('deck.scratch', { deck: 'A', phase, positionMs, gestureId });
  async function until(predicate, timeout = 4000) {
    const start = performance.now();
    let state;
    do {
      state = await snapshot();
      if (predicate(state)) return state;
      await delay(25);
    } while (performance.now() - start < timeout);
    assert.fail(`Snapshot condition timed out: ${JSON.stringify(state.decks.A)}`);
  }
  async function hold(positionMs, ms, gesture = 'main') {
    for (let elapsed = 0; elapsed < ms; elapsed += 200) { await scratch('move', positionMs, gesture); await delay(200); }
  }
  async function move(from, to, ms, gesture = 'main') {
    const start = performance.now();
    for (let step = 1; step <= 50; step++) {
      await scratch('move', from + (to - from) * step / 50, gesture);
      await delay(Math.max(0, start + step * ms / 50 - performance.now()));
    }
  }
  const evidence = {};
  try {
    hello = await command('session.hello');
    await until(state => state.audio.applied);
    await command('deck.load', { deck: 'A', track: { trackId: 'scratch-source', path: fixture } });
    await until(state => state.decks.A.track?.trackId === 'scratch-source');
    await command('deck.pause', { deck: 'A' });
    await command('deck.seek', { deck: 'A', positionMs: 12000 });
    await until(state => Math.abs(state.decks.A.positionMs - 12000) < 50);
    assert.equal((await snapshot()).decks.A.track.sampleRateHz, 48000);

    for (const params of [
      { phase: 'invalid', positionMs: 0, gestureId: 'x' },
      { phase: 'begin', positionMs: 1, gestureId: 'x' },
      { phase: 'begin', positionMs: 0, gestureId: '' },
      { phase: 'move', positionMs: 60001, gestureId: 'x' },
      { phase: 'move', positionMs: null, gestureId: 'x' },
      { phase: 'move', positionMs: '10', gestureId: 'x' },
    ]) await command('deck.scratch', { deck: 'A', ...params }, 'invalid_params');

    // Small, continuous controller movements must not become repeated stops.
    // 0.4 ms per packet is four counts at the application's 0.10 ms/count.
    await scratch('begin', 0, 'fine-motion');
    await hold(0, 200, 'fine-motion');
    await command('deck.timing.trace', { deck: 'A' });
    for (let step = 1; step <= 50; step++) {
      await scratch('move', step * 0.4, 'fine-motion');
      await delay(20);
    }
    const fineTrace = (await command('deck.timing.trace', { deck: 'A' })).rows
      .filter(row => row.held && row.targetMs > 12004);
    const stops = fineTrace.filter(row => Math.abs(row.commandedSpeed) < 0.000001).length;
    console.log(JSON.stringify({ fineMotion: { callbacks: fineTrace.length, stops } }));
    assert(fineTrace.length > 20, 'Fine motion produced enough audio callbacks');
    assert(stops / fineTrace.length < 0.1, `Continuous fine motion must not gate to zero: ${stops}/${fineTrace.length}`);
    await scratch('end', 20, 'fine-motion');
    await until(state => !state.decks.A.scratching);
    await command('deck.seek', { deck: 'A', positionMs: 12000 });
    await until(state => Math.abs(state.decks.A.positionMs - 12000) < 5);


    await command('recording.start');
    const recording = (await until(state => state.recording.active)).recording;
    const recordStart = performance.now() - recording.elapsedMs;
    const time = () => performance.now() - recordStart;
    await scratch('begin', 0);
    await until(state => state.decks.A.scratching);
    await hold(0, 600);
    const forwardAt = time();
    await move(0, 1200, 1000);
    await hold(1200, 800);
    const forward = (await snapshot()).decks.A;
    assert.equal(forward.status, 'paused');
    assert(Math.abs(forward.positionMs - 13200) < 120, `Forward position: ${forward.positionMs}`);
    const backwardAt = time();
    await move(1200, -1200, 1000);
    await hold(-1200, 800);
    const backward = (await snapshot()).decks.A;
    if (process.env.DJALY_MIXXX_TIMING_TRACE === '1') {
      const timing = await command('deck.timing.trace', { deck: 'A' });
      console.log(JSON.stringify({ pausedHoldTrace: timing.rows.slice(-40) }));
    }
    assert.equal(backward.status, 'paused');
    assert(Math.abs(backward.positionMs - 10800) < 120, `Backward position: ${backward.positionMs}`);
    await scratch('end', -1200);
    await until(state => !state.decks.A.scratching);
    const releaseAt = time();
    await delay(1400);
    assert(Math.abs((await snapshot()).decks.A.positionMs - backward.positionMs) < 35, 'Paused release must stay stopped');
    await command('recording.stop');
    // Mixxx's sidechain wakes after roughly 0.6s of buffered PCM; stop reports
    // command state before that worker has finalized the WAV header.
    await delay(1000);
    const recorded = await readFile(recording.path);
    // EngineRecord includes the entire already buffered chunk when it opens,
    // so its file begins BEFORE the active notification. Align to the first
    // audible motion; the preceding held/paused deck produces no signal.
    let onset;
    for (let ms = 0; ms < forwardAt + 1500; ms += 10) {
      if (pcmWindow(recorded, ms, ms + 20).rms > 100) { onset = ms; break; }
    }
    assert.notEqual(onset, undefined, 'Paused scratch has an audible PCM onset');
    const shift = onset - forwardAt;
    const forwardPcm = pcmWindow(recorded, forwardAt + shift + 250, forwardAt + shift + 750);
    const backwardPcm = pcmWindow(recorded, backwardAt + shift + 250, backwardAt + shift + 750);
    const holdPcm = pcmWindow(recorded, backwardAt + shift + 1450, backwardAt + shift + 1750);
    const releasePcm = pcmWindow(recorded, releaseAt + shift + 200, releaseAt + shift + 500);
    assert(forwardPcm.rms > 100, `Forward scratch must produce PCM: ${JSON.stringify(forwardPcm)}`);
    assert(backwardPcm.rms > 100, `Backward scratch must produce PCM: ${JSON.stringify(backwardPcm)}`);
    assert(holdPcm.rms < forwardPcm.rms * 0.1, `Held paused scratch must settle: ${JSON.stringify(holdPcm)}`);
    assert(releasePcm.rms < forwardPcm.rms * 0.1, 'Paused release must be silent');
    assert(forwardPcm.frequencyHz > 400 && forwardPcm.frequencyHz < 650, `1.2x source motion changes the 440Hz tone pitch: ${JSON.stringify(forwardPcm)}`);
    assert(backwardPcm.frequencyHz > 850 && backwardPcm.frequencyHz < 1250, `2.4x reverse source motion changes tone pitch: ${JSON.stringify(backwardPcm)}`);
    evidence.paused = { forwardMs: forward.positionMs, backwardMs: backward.positionMs, recorderOffsetMs: shift, forwardPcm, backwardPcm, holdPcm, releasePcm };

    await command('deck.play', { deck: 'A' });
    await delay(300);
    await scratch('begin', 0, 'playing');
    await hold(0, 600, 'playing');
    const held = (await snapshot()).decks.A;
    await hold(0, 1800, 'playing');
    const stillHeld = (await snapshot()).decks.A;
    assert(stillHeld.scratching, '250ms heartbeat must keep a >1500ms hold alive');
    assert.equal(stillHeld.status, 'playing');
    assert(Math.abs(stillHeld.positionMs - held.positionMs) < 50, 'Held playing deck must stop its platter');
    await move(0, 800, 800, 'playing');
    await hold(800, 400, 'playing');
    const playingForward = (await snapshot()).decks.A;
    assert(playingForward.positionMs > held.positionMs + 650);
    await move(800, -400, 800, 'playing');
    await hold(-400, 400, 'playing');
    const playingBackward = (await snapshot()).decks.A;
    assert(playingBackward.positionMs < held.positionMs - 250);
    await scratch('end', -400, 'playing');
    await until(state => !state.decks.A.scratching);
    await delay(350);
    const released = (await snapshot()).decks.A;
    assert.equal(released.status, 'playing');
    assert(released.positionMs > playingBackward.positionMs + 250, 'Release resumes previously playing transport');
    evidence.playing = { heldMs: held.positionMs, forwardMs: playingForward.positionMs, backwardMs: playingBackward.positionMs, releaseMs: released.positionMs };

    // 速いドラッグ: プラッターは要求位置へ漸近するだけなので、離した瞬間に切ると
    // 置いた場所より手前で止まり、さらに慣性で滑る。掴んだ位置＋移動量へ着地すること。
    await command('deck.pause', { deck: 'A' });
    await delay(250);
    const flickBase = (await snapshot()).decks.A.positionMs;
    await scratch('begin', 0, 'flick');
    await until(state => state.decks.A.scratching);
    await move(0, -900, 150, 'flick');
    await scratch('end', -900, 'flick');
    await until(state => !state.decks.A.scratching);
    await delay(400);
    const flicked = (await snapshot()).decks.A.positionMs;
    assert(Math.abs(flicked - (flickBase - 900)) < 60,
      `Quick paused drag lands where it was dropped: ${flicked} vs ${flickBase - 900}`);
    await delay(600);
    assert(Math.abs((await snapshot()).decks.A.positionMs - flicked) < 35, 'Released platter must not coast');

    // 再生中の速いドラッグ: 離したあとは等速に戻り、慣性で余分に進まないこと。
    await command('deck.play', { deck: 'A' });
    await delay(400);
    await scratch('begin', 0, 'flick-play');
    await until(state => state.decks.A.scratching);
    await move(0, -900, 150, 'flick-play');
    await scratch('end', -900, 'flick-play');
    await until(state => !state.decks.A.scratching);
    await delay(300);
    const resumed = (await snapshot()).decks.A.positionMs;
    const resumedAt = performance.now();
    await delay(600);
    const later = (await snapshot()).decks.A;
    const advanced = later.positionMs - resumed;
    const elapsed = performance.now() - resumedAt;
    assert.equal(later.status, 'playing');
    assert(Math.abs(advanced - elapsed) < 90,
      `Playback resumes at 1x with no throw: advanced ${advanced.toFixed(0)}ms in ${elapsed.toFixed(0)}ms`);
    evidence.flick = { flickBase, flicked, advanced, elapsed };

    await command('deck.pause', { deck: 'A' });
    await delay(200);
    // 一定速度の連続入力では音声レートも一定でなければならない。目標が階段の
    // ままだと、パケット到着でレートが跳ね次の到着まで減衰する鋸歯になり、
    // 入力間隔の周期で速度が変調されて低音の輪郭が濁る。5 点移動平均からの
    // ずれ / 平均速度で「がたつき」を測る。旧実装では 5% 前後になる。
    await scratch('begin', 0, 'steady-motion');
    await until(state => state.decks.A.scratching);
    await hold(0, 200, 'steady-motion');
    await command('deck.timing.trace', { deck: 'A' });
    const steadyStart = performance.now();
    let steadyPosition = 0;
    while (steadyPosition < 1200) {
      steadyPosition = performance.now() - steadyStart;
      await scratch('move', steadyPosition, 'steady-motion');
      await delay(Math.max(0, 10 - (performance.now() - steadyStart - steadyPosition)));
    }
    // 動き出しの追い付き（約 300ms）は定常のがたつきではないので外す。
    const steady = (await command('deck.timing.trace', { deck: 'A' })).rows
      .filter(row => row.held && row.scratching).slice(55, -5).map(row => row.speed);
    assert(steady.length > 60, `Steady motion produced enough audio callbacks: ${steady.length}`);
    const level = steady.reduce((sum, value) => sum + Math.abs(value), 0) / steady.length;
    const deviations = steady.slice(2, -2).map((value, index) =>
      value - steady.slice(index, index + 5).reduce((sum, item) => sum + item, 0) / 5);
    const roughness = Math.sqrt(deviations.reduce((sum, value) => sum + value * value, 0) / deviations.length) / level;
    console.log(JSON.stringify({ steadyMotion: { callbacks: steady.length, level: Number(level.toFixed(3)), roughness: Number(roughness.toFixed(4)) } }));
    assert(level > 0.7, `Steady 1x input must track at playback speed: ${level}`);
    // 旧実装ではここが 5% 前後になる（入力間隔ごとの速度変調）。
    assert(roughness < 0.02, `Steady scratch input must not modulate playback rate: ${roughness}`);
    await scratch('end', steadyPosition, 'steady-motion');
    await until(state => !state.decks.A.scratching);

    // UI スレッドが詰まって位置更新の間隔がばらつくと、階段目標を P 制御だけで
    // 追う実装は谷間でレートがゼロ付近まで落ち、バックスピン中に音が切れる。
    // 5〜70ms のジッタで一定速度の逆回転を送り、レートが落ちないことを見る。
    await scratch('begin', 0, 'jitter-spin');
    await until(state => state.decks.A.scratching);
    await hold(0, 200, 'jitter-spin');
    await command('deck.timing.trace', { deck: 'A' });
    const spinStart = performance.now();
    let spinPosition = 0;
    while (performance.now() - spinStart < 900) {
      spinPosition = (performance.now() - spinStart) * -6;
      await scratch('move', spinPosition, 'jitter-spin');
      await delay(5 + Math.random() * 65);
    }
    const spin = (await command('deck.timing.trace', { deck: 'A' })).rows
      .filter(row => row.held && row.scratching).slice(30, -5).map(row => Math.abs(row.speed));
    assert(spin.length > 60, `Jittered backspin produced enough audio callbacks: ${spin.length}`);
    const spinMean = spin.reduce((sum, value) => sum + value, 0) / spin.length;
    const floor = Math.min(...spin) / spinMean;
    console.log(JSON.stringify({ jitterSpin: { callbacks: spin.length, mean: Number(spinMean.toFixed(2)), floor: Number(floor.toFixed(3)) } }));
    // 旧実装ではここが 0.1 前後まで落ちる（パケット間でプラッターが止まる）。
    assert(floor > 0.5, `Jittered input must not stall the platter mid-spin: ${floor}`);
    await scratch('end', spinPosition, 'jitter-spin');
    await until(state => !state.decks.A.scratching);

    await command('deck.pause', { deck: 'A' });
    await delay(200);
    const burstBase = (await snapshot()).decks.A.positionMs;
    // Same pipe turn: initial move may not replace the audio callback baseline.
    await Promise.all([scratch('begin', 0, 'old'), scratch('move', 900, 'old')]);
    await hold(900, 800, 'old');
    assert(Math.abs((await snapshot()).decks.A.positionMs - burstBase - 900) < 120, 'Coalesced begin/move preserves full relative travel');
    await scratch('begin', 0, 'new');
    assert.equal((await scratch('move', -5000, 'old')).accepted, false);
    assert.equal((await scratch('end', 0, 'old')).accepted, false);
    await hold(0, 500, 'new');
    const newBase = (await snapshot()).decks.A.positionMs;
    assert((await snapshot()).decks.A.scratching, 'Late end did not release newer gesture');
    await scratch('begin', 0, 'new'); // Idempotent begin must not reset it.
    await move(0, -600, 500, 'new');
    await hold(-600, 500, 'new');
    assert(Math.abs((await snapshot()).decks.A.positionMs - newBase + 600) < 120);
    await until(state => !state.decks.A.scratching, 2500); // No heartbeat: watchdog.
    assert.equal((await scratch('move', 1000, 'new')).accepted, false, 'Expired gesture cannot re-grab');

    // Bound large jumps before the PID and exercise a new begin while the old
    // scratch is fast enough to enter Mixxx's release/throw inertia branch.
    await scratch('begin', 0, 'throw');
    let maxPingMs = 0;
    for (let i = 0; i < 12; i++) {
      await scratch('move', i % 2 ? 60000 : -60000, 'throw');
      const sentAt = performance.now();
      await command('engine.ping');
      maxPingMs = Math.max(maxPingMs, performance.now() - sentAt);
      await delay(40);
    }
    assert(maxPingMs < 1000, 'Bounded extreme moves must not stall command processing');
    await Promise.all([scratch('end', 60000, 'throw'), scratch('begin', 0, 'regrab')]);
    await hold(0, 600, 'regrab');
    const regrabBase = (await snapshot()).decks.A.positionMs;
    await move(0, 300, 400, 'regrab');
    await hold(300, 600, 'regrab');
    assert(Math.abs((await snapshot()).decks.A.positionMs - regrabBase - 300) < 120, 'Re-grab after a fast throw establishes its own baseline');
    await scratch('end', 300, 'regrab');
    await until(state => !state.decks.A.scratching);
    evidence.maxPingMsDuringExtremeMoves = maxPingMs;

    await scratch('begin', 0, 'session');
    await until(state => state.decks.A.scratching);
    hello = await command('session.hello');
    await until(state => !state.decks.A.scratching);
    await scratch('begin', 0, 'reload');
    await until(state => state.decks.A.scratching);
    const beatTimesMs = [];
    for (let ms = 0, i = 0; ms < 30000; ms += 450 + (i++ % 4) * 50) beatTimesMs.push(ms);
    await command('deck.load', { deck: 'A', track: { trackId: 'replacement', path: fixture, beatTimesMs } });
    await until(state => state.decks.A.track?.trackId === 'replacement');
    assert.equal((await snapshot()).decks.A.scratching, false, 'replacement load releases the platter');
    assert.equal((await scratch('move', 1000, 'reload')).accepted, false, 'stale gesture after reload is rejected');

    await command('deck.load', { deck: 'B', track: { trackId: 'telemetry-B', path: fixture } });
    await until(state => state.decks.B.track?.trackId === 'telemetry-B');
    await command('deck.play', { deck: 'A' });
    await command('deck.play', { deck: 'B' });
    await until(state => state.decks.A.positionMs > 100 && state.decks.B.positionMs > 100);
    observeTelemetry = true;
    await delay(1000);
    await scratch('begin', 0, 'telemetry');
    await move(0, 2800, 2000, 'telemetry');
    await hold(2800, 400, 'telemetry');
    await scratch('end', 2800, 'telemetry');
    await until(state => !state.decks.A.scratching);
    observeTelemetry = false;
    assert.equal(telemetry.fullStates, 0, 'Variable BPM/scratch updates must not resend the full track/grid');
    assert(telemetry.positionEvents > 20);
    assert(observedBpms.size >= 3, `Variable BPM must arrive in lightweight telemetry: ${[...observedBpms]}`);
    assert(telemetry.maxPositionBytes < 1200, 'Position events have bounded small payloads');
    assert(telemetry.batchedEvents > 0, 'Independent deck changes share one position event');
    evidence.telemetry = { ...telemetry, distinctBpms: [...observedBpms] };
    await command('deck.pause', { deck: 'A' });
    await command('deck.unload', { deck: 'B' });
    await scratch('begin', 0, 'unload');
    await until(state => state.decks.A.scratching);
    await command('deck.unload', { deck: 'A' });
    assert.equal((await snapshot()).decks.A.scratching, false);
    evidence.gestureRace = true; evidence.watchdog = true; evidence.lifecycle = true;
    console.log(JSON.stringify(evidence));
  } finally {
    child.stdin.end();
    let outcome = await Promise.race([exited, delay(3000).then(() => null)]);
    if (!outcome) { child.kill('SIGTERM'); outcome = await Promise.race([exited, delay(3000).then(() => null)]); }
    await rm(directory, { recursive: true, force: true });
    assert.equal(outcome?.code, 0, stderr);
  }
});
