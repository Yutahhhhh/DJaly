import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { createInterface } from 'node:readline';
import { mkdtemp, writeFile, readFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import test from 'node:test';

const binary = process.env.DJALY_TEST_HOST || path.resolve(import.meta.dirname, '../build-upstream/djaly-mixxx-engine-host');
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));

test('real-track scratch response and reversal latency', { timeout: 45000, skip: !process.env.DJALY_SCRATCH_TRACK }, async () => {
  const directory = await mkdtemp(path.join(tmpdir(), 'djaly-native-scratch-'));
  const input=process.env.DJALY_SCRATCH_TRACK;
  const child = spawn(binary, [], { env: { ...process.env, DJALY_MIXXX_TIMING_TRACE: '1', DJALY_MIXXX_OUTPUT_DEVICE: process.env.DJALY_MIXXX_OUTPUT_DEVICE || 'BlackHole 2ch', DJALY_MIXXX_RECORDING_DIR: directory } });
  let stderr = '', id = 0, hello;
  const pending = new Map();
  child.stderr.on('data', data => { stderr = (stderr + data).slice(-12000); });
  const exited = new Promise(resolve => child.once('exit', (code, signal) => resolve({ code, signal })));
  createInterface({ input: child.stdout }).on('line', line => {
    const message = JSON.parse(line);
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
  try {
    hello=await command('session.hello');
    await until(s=>s.audio.applied);
    await command('deck.load',{deck:'A',track:{trackId:'real-track',path:input}});
    await until(s=>s.decks.A.track?.trackId==='real-track');
    await command('deck.pause',{deck:'A'});
    await command('deck.seek',{deck:'A',positionMs:60000});
    await delay(200);
    await command('recording.start');
    const recording=(await until(s=>s.recording.active)).recording;
    await scratch('begin',0);
    await hold(0,200);
    await command('deck.timing.trace',{deck:'A'});
    let position=0;
    // Repeated short 100ms strokes. Include real command arrival timing rather
    // than estimating responsiveness from average playback speed.
    for(let stroke=0;stroke<8;stroke++) {
      const sign=stroke%2 ? -1 : 1;
      for(let packet=0;packet<25;packet++) {
        position+=sign*4;
        await scratch('move',position);
        await delay(4);
      }
    }
    await delay(250);
    const rows=(await command('deck.timing.trace',{deck:'A'})).rows;
    const latencies=[];
    let direction=0;
    for(let i=1;i<rows.length;i++) {
      const delta=rows[i].targetMs-rows[i-1].targetMs;
      if(Math.abs(delta)<.01) continue;
      const next=Math.sign(delta);
      if(direction && next!==direction) {
        const changed=rows.slice(i).find(row=>Math.sign(row.speed)===next && Math.abs(row.speed)>.05);
        assert(changed,'Every stroke reversal must reach the audio output');
        latencies.push(changed.audioMs-rows[i].audioMs);
      }
      direction=next;
    }
    await scratch('end',position);
    await delay(400);
    await command('recording.stop');
    await delay(1000);
    const audio=await readFile(recording.path);
    // Keep the private local recording and trace for comparison. Source audio
    // is never changed and no music is checked into the repository.
    let lastMotion=0;
    for(let i=1;i<rows.length;i++) if(Math.abs(rows[i].targetMs-rows[i-1].targetMs)>.01) lastMotion=i;
    const stopped=rows.findIndex((row,i)=>i>=lastMotion && i+5<=rows.length && rows.slice(i,i+5).every(sample=>Math.abs(sample.speed)<.02));
    const stopMs=stopped<0 ? null : rows[stopped].audioMs-rows[lastMotion].audioMs;
    const evidence={input,latencies,maxReversalMs:Math.max(...latencies),stopMs,rows,recording:recording.path};
    await writeFile(path.join(directory,'response.json'),JSON.stringify(evidence));
    console.log(JSON.stringify({directory,latencies,maxReversalMs:evidence.maxReversalMs,stopMs,recordedBytes:audio.length}));
    assert(latencies.length>=7);
    assert(evidence.maxReversalMs<=12,`Audio reversal is delayed by ${evidence.maxReversalMs.toFixed(1)}ms after the input reaches the audio callback`);
    assert(stopMs!==null && stopMs<=70,`Stopped hand must settle within 70ms; observed ${stopMs}`);
  } finally {
    child.stdin.end();
    let outcome=await Promise.race([exited,delay(3000).then(()=>null)]);
    if(!outcome){child.kill('SIGTERM');outcome=await Promise.race([exited,delay(3000).then(()=>null)]);}
    assert.equal(outcome?.code,0,stderr);
  }
});
