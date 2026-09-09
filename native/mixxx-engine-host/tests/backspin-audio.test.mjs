import assert from 'node:assert/strict';
import { spawn, spawnSync } from 'node:child_process';
import { createInterface } from 'node:readline';
import { mkdtemp, writeFile, readFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import test from 'node:test';
import { Ddj1000Runtime } from '../../../src/services/midi/ddj1000-runtime.ts';
import { Ddj1000Decoder } from '../../../src/services/midi/ddj1000.ts';
import { ScratchCommandQueue } from '../../../src/services/dj-engine/scratch-command-queue.ts';

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

test('fast reverse scratch stays audible in recorded PCM', { timeout: 45000 }, async () => {
  const directory = await mkdtemp(path.join(tmpdir(), 'djaly-native-scratch-'));
  const fixture = path.join(directory, 'mono-48000.wav');
  // A mono source at 48 kHz deliberately differs from the stereo 44.1 kHz
  // engine. Scratch positions must still use SOURCE frames * two.
  const longTrack = process.env.DJALY_SCRATCH_LONG === '1';
  const realTrack = process.env.DJALY_SCRATCH_TRACK;
  const origin = realTrack ? 60000 : longTrack ? 240000 : 24000;
  const rate = 48000, frames = rate * (longTrack ? 300 : 30);
  const wave = Buffer.alloc(44 + frames * 2);
  wave.write('RIFF'); wave.writeUInt32LE(wave.length - 8, 4); wave.write('WAVEfmt ', 8);
  wave.writeUInt32LE(16, 16); wave.writeUInt16LE(1, 20); wave.writeUInt16LE(1, 22);
  wave.writeUInt32LE(rate, 24); wave.writeUInt32LE(rate * 2, 28);
  wave.writeUInt16LE(2, 32); wave.writeUInt16LE(16, 34); wave.write('data', 36); wave.writeUInt32LE(frames * 2, 40);
  for (let i = 0; i < frames; i++) wave.writeInt16LE(Math.round(4000 * Math.sin(2 * Math.PI * 440 * i / rate)), 44 + i * 2);
  await writeFile(fixture, wave);
  const codec = process.env.DJALY_SCRATCH_CODEC;
  let input = realTrack || fixture;
  if (codec) {
    assert(['mp3', 'm4a'].includes(codec), 'Supported test codecs: mp3, m4a');
    input = path.join(directory, `encoded.${codec}`);
    const encoded = spawnSync('ffmpeg', ['-v', 'error', '-i', fixture, '-y', input], {encoding:'utf8'});
    assert.equal(encoded.status, 0, encoded.stderr || String(encoded.error));
  }
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
  try {
    hello = await command('session.hello');
    await until(state=>state.audio.applied);
    await command('deck.load',{deck:'A',track:{trackId:'spin-audio',path:input,bpm:120,beatgridOffsetMs:0}});
    await until(state=>state.decks.A.track?.trackId==='spin-audio');
    await command('deck.pause',{deck:'A'});
    await command('deck.seek',{deck:'A',positionMs:origin});
    await delay(200);
    await command('recording.start');
    const recording=(await until(state=>state.recording.active)).recording;
    const start=performance.now()-recording.elapsedMs;
    const at=()=>performance.now()-start;
    const windows=[];
    for(const speed of [6,12,16]) {
      await command('deck.seek',{deck:'A',positionMs:origin - (longTrack ? speed * 10000 : 0)});
      await delay(200);
      await scratch('begin',0);
      await hold(0,400);
      const begin=at();
      await move(0,-speed*1000,1000);
      windows.push({speed,begin});
      await hold(-speed*1000,400);
      await scratch('end',-speed*1000);
      await delay(300);
    }
    await command('recording.stop');
    await delay(1100);
    const recorded=await readFile(recording.path);
    let onset;
    for(let ms=0;ms<windows[0].begin+1500;ms+=10) {
      if(pcmWindow(recorded,ms,ms+20).rms>100){onset=ms;break;}
    }
    assert.notEqual(onset,undefined,'Backspin must produce audible output');
    const offset=onset-windows[0].begin;
    for(const {speed,begin} of windows) {
      const levels=[];
      for(let ms=begin+offset+250;ms<begin+offset+850;ms+=20) levels.push(pcmWindow(recorded,ms,ms+20).rms);
      const minimum=Math.min(...levels);
      console.log(JSON.stringify({speed,minimumRms:minimum}));
      // Real music can contain intentional gaps; require audible signal over
      // the stroke, while the continuous-tone fixture checks every window.
      assert(realTrack ? levels.some(level=>level>100) : minimum>100,
        `Reverse ${speed}x must remain audible: ${minimum}`);
    }
    const diagnosticPath=path.join(tmpdir(),`djaly-scratch-${child.pid}.json`);
    const diagnosis=JSON.parse(await readFile(diagnosticPath,'utf8'));
    assert(diagnosis.samples.some(sample=>sample.masterPeak>0),
      'Diagnostic output meter must read the real Main bus rather than a nonexistent legacy key');
    const rows=diagnosis.samples.map(sample=>sample.decks.A);
    assert(rows.some(row=>row.speed < -1 && row.preFaderPeak > .01),
      'Automatic diagnostics must capture audible reverse audio before the mixer');
    const beforeSilent=Math.max(...rows.map(row=>row.silentMovingBuffers));
    // Deliberate out-of-file movement: the waveform moves but the source is
    // silent. Diagnostics must distinguish this from mixer muting in-file.
    await command('deck.seek',{deck:'A',positionMs:0});
    await delay(100);
    await scratch('begin',0);
    await move(0,-1000,500);
    await delay(300);
    await scratch('end',-1000);
    await delay(350);
    const silent=JSON.parse(await readFile(diagnosticPath,'utf8')).samples.map(sample=>sample.decks.A);
    assert(silent.some(row=>row.positionMs<0 && row.silentMovingBuffers>beforeSilent),
      'Moving outside the source must be visible as negative position plus silent audio buffers');
    await command('deck.seek',{deck:'A',positionMs:24000});
    await delay(150);
    let latest=await snapshot();
    const errors=[];
    const queue=new ScratchCommandQueue(params=>command('deck.scratch',params));
    const client={
      getState:()=>({snapshot:latest}), getSessionId:()=>hello.sessionId, getDeckGeneration:()=>0,
      scratch:(deck,phase,positionMs,gestureId)=>queue.enqueue({deck,phase,positionMs,gestureId}),
      pitchbend:(deck,amount)=>command('deck.pitchbend',{deck,amount}),
    };
    const runtime=new Ddj1000Runtime(client,()=>({activate:()=>{},library:()=>{},error:e=>errors.push(e),cuePoints:{A:0,B:0,C:0,D:0}}));
    runtime.jogSensitivity=1;
    const decoder=new Ddj1000Decoder();
    const midi=bytes=>decoder.feed(bytes).forEach(action=>runtime.dispatch(action));
    const began=Date.now();
    try {
      midi([0x90,0x36,127]);
      for(let step=0;step<30;step++) {
        await delay(20);
        for(let n=0;n<4;n++) midi([0xb0,0x22,34]);
        if(step===5) midi([0x90,0x36,0]);
        if(step>6) {
          latest=await snapshot();
          assert.equal(latest.decks.A.scratching,true,'Continuing reverse packets must survive touch release');
          assert.equal(latest.decks.A.rate,1,'Reverse spin must not change tempo');
        }
      }
      await delay(400);
      latest=await snapshot();
      assert.equal(latest.decks.A.scratching,false,'Packet silence must finish the spin');
      const traced=JSON.parse(await readFile(diagnosticPath,'utf8')).samples.filter(row=>row.timeMs>began+250);
      assert(traced.some(row=>row.decks.A.speed < -1 && row.decks.A.preFaderPeak>.01),
        'Reverse audio must remain audible after physical touch release');
      assert.deepEqual(errors,[]);
    } finally {runtime.dispose();}
  } finally {
    child.stdin.end();
    let outcome=await Promise.race([exited,delay(3000).then(()=>null)]);
    if(!outcome){child.kill('SIGTERM');outcome=await Promise.race([exited,delay(3000).then(()=>null)]);}
    if (process.env.DJALY_KEEP_SCRATCH_AUDIO === '1') console.log(JSON.stringify({directory,input}));
    else await rm(directory,{recursive:true,force:true});
    await rm(path.join(tmpdir(),`djaly-scratch-${child.pid}.json`),{force:true});
    assert.equal(outcome?.code,0,stderr);
  }
});
