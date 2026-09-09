// End-to-end mapping -> real host. Silent fixture; no physical audio emitted.
// Opt in to the hardware route with DJALY_MIXXX_OUTPUT_DEVICE=DDJ-1000.
import test from 'node:test';
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { mkdtemp, writeFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { createInterface } from 'node:readline';
import { Ddj1000Decoder } from '../../../src/services/midi/ddj1000.ts';
import { Ddj1000Runtime } from '../../../src/services/midi/ddj1000-runtime.ts';
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
test('sampler loads, plays, stops, ejects and rejects stale gestures independently of decks', { timeout: 30000 }, async () => {
  const directory = await mkdtemp(path.join(tmpdir(), 'djaly-ddj-integration-'));
  const wav = Buffer.alloc(44 + 44100 * 4 * 20);
  wav.write('RIFF'); wav.writeUInt32LE(wav.length - 8, 4); wav.write('WAVEfmt ', 8);
  wav.writeUInt32LE(16, 16); wav.writeUInt16LE(1, 20); wav.writeUInt16LE(2, 22);
  wav.writeUInt32LE(44100, 24); wav.writeUInt32LE(176400, 28); wav.writeUInt16LE(4, 32); wav.writeUInt16LE(16, 34);
  wav.write('data', 36); wav.writeUInt32LE(wav.length - 44, 40);
  const file = path.join(directory, 'silence.wav'); await writeFile(file, wav);
  const output = process.env.DJALY_MIXXX_OUTPUT_DEVICE || 'BlackHole 2ch';
  const binary = process.env.DJALY_TEST_HOST || path.resolve(import.meta.dirname, '../build-upstream/djaly-mixxx-engine-host');
  const child = spawn(binary, [], { env: { ...process.env, DJALY_MIXXX_OUTPUT_DEVICE: output, DJALY_MIXXX_RECORDING_DIR: directory } });
  let id = 0, hello, snapshot, stderr = '', runtime;
  const pending = new Map(), errors = [];
  child.stderr.on('data', bytes => { stderr += bytes; });
  const exited = new Promise(resolve => child.once('exit', resolve));
  createInterface({ input: child.stdout }).on('line', line => { const m = JSON.parse(line); if (m.kind !== 'event') pending.get(m.id)?.(m); });
  const command = async (op, params = {}) => {
    const next = ++id;
    const reply = new Promise((resolve, reject) => {
      const timer = setTimeout(() => { pending.delete(next); reject(new Error(`Timeout ${op}: ${stderr.slice(-800)}`)); }, 8000);
      pending.set(next, m => { clearTimeout(timer); pending.delete(next); m.kind === 'error' ? reject(new Error(JSON.stringify(m))) : resolve(m.data ?? m); });
    });
    child.stdin.write(JSON.stringify({ id: next, op, params, ...(hello ? { engineId: hello.engineId, sessionId: hello.sessionId } : {}) }) + '\n');
    return reply;
  };
  const refresh = async () => { snapshot = await command('state.snapshot'); return snapshot; };
  const until = async predicate => {
    for (let n = 0; n < 100; n++) { await refresh(); if (predicate(snapshot)) return; await delay(25); }
    throw new Error('State timeout: ' + JSON.stringify(snapshot));
  };
  try {
    hello = await command('session.hello'); await until(s => s.audio.applied);
    let bank = await command('sampler.state');
    assert.equal(bank.slots.length, 16);
    await assert.rejects(command('sampler.load', {slot:16,path:file}));
    await assert.rejects(command('sampler.load', {slot:0,path:'relative.wav'}));
    await assert.rejects(command('sampler.play', {slot:0}));
    await command('sampler.load', {slot:0,path:file});
    await command('sampler.load', {slot:15,path:file});
    for (let i=0;i<150;i++) { bank=await command('sampler.state'); if(bank.slots[0].status==='ready' && bank.slots[15].status==='ready') break; await delay(20); }
    assert.equal(bank.slots[0].status,'ready'); assert.equal(bank.slots[15].status,'ready');
    const revision=bank.slots[0].revision;
    await command('sampler.play', {slot:0,revision}); await command('sampler.play', {slot:15});
    await delay(100); bank=await command('sampler.state');
    assert.equal(bank.slots[0].status,'playing'); assert.equal(bank.slots[15].status,'playing');
    bank=await command('sampler.gain',{gain:0.25}); assert.equal(bank.gain,0.25);
    await assert.rejects(command('sampler.gain',{gain:2}));
    await command('sampler.stopAll'); await delay(50);
    bank=await command('sampler.state'); assert.equal(bank.slots[0].status,'ready'); assert.equal(bank.slots[15].status,'ready');
    await command('sampler.eject',{slot:0});
    await assert.rejects(command('sampler.play',{slot:0,revision}));
    bank=await command('sampler.state'); assert.equal(bank.slots[0].status,'empty');
    assert.equal((await refresh()).decks.A.status,'empty');
    await command('sampler.bank',{bank:1});
    assert.equal((await command('sampler.state')).slots[15].status,'empty');
    await command('sampler.bank',{bank:0});
    assert.equal((await command('sampler.state')).slots[15].status,'ready');
    await command('deck.load',{deck:'A',track:{trackId:'keys',path:file,durationMs:20000,musicalKey:'C',bpm:120,beatgridOffsetMs:0,beatsPerBar:4}});
    await until(s=>s.decks.A.track && s.decks.A.status!=='loading');
    await command('deck.key.shift',{deck:'A',semitones:7});
    await until(s=>Math.abs(s.decks.A.keyShift-7)<0.01);
    await command('deck.key.reset',{deck:'A'}); await until(s=>Math.abs(s.decks.A.keyShift)<0.01);
    await command('deck.slip.set',{deck:'A',enabled:true}); await until(s=>s.decks.A.slip);
    await command('deck.reverse.set',{deck:'A',enabled:true}); await until(s=>s.decks.A.reverse);
    await command('deck.reverse.set',{deck:'A',enabled:false}); await until(s=>!s.decks.A.reverse);
    await command('deck.hotcue.set',{deck:'A',index:15,positionMs:1000});
    await until(s=>s.decks.A.hotCues[15]===1000);
    await command('deck.hotcue.jump',{deck:'A',index:15}); await until(s=>Math.abs(s.decks.A.positionMs-1000)<20);
    await command('mixer.fx.set',{deck:'A',effect:'reverb',enabled:true,mix:0.5});
    let mixer = await command('mixer.beatfx.set',{effect:'echo',target:'master',enabled:true,mix:0.3,beats:0.5});
    assert.equal(mixer.beatFx.target,'master'); assert.equal(mixer.beatFx.enabled,true);
    assert.equal(mixer.channels.A.fx.effect,'reverb'); assert.equal(mixer.channels.A.fx.enabled,true);
    mixer = await command('mixer.beatfx.set',{target:'sampler'}); assert.equal(mixer.beatFx.target,'sampler');
    await command('mixer.beatfx.set',{enabled:false});
    await assert.rejects(command('deck.key.shift',{deck:'A',semitones:13}));
    await assert.rejects(command('deck.reverse.set',{deck:'A',enabled:1}));
  } finally { runtime?.dispose(); child.stdin.end(); await Promise.race([exited,delay(1000)]); child.kill(); await rm(directory,{recursive:true,force:true}); }
});
