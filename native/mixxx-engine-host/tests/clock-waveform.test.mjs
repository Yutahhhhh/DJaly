import test from 'node:test';
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {createInterface} from 'node:readline';
import {mkdtemp,writeFile,readFile,appendFile} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import path from 'node:path';
import {parseTile,parsePcmWindow} from '../../../src/services/waveform/protocol.ts';
import {parseClockPoint} from '../../../src/types/deck-performance.ts';
const delay=ms=>new Promise(r=>setTimeout(r,ms));
test('real decoder stereo tiles and callback source-frame clock agree across rate conversion', {timeout:30000},async()=>{
 const directory=await mkdtemp(path.join(tmpdir(),'plumdeck-clock-waveform-'));
 const rate=48000,frames=rate*4+3,bytes=Buffer.alloc(44+frames*4);
 bytes.write('RIFF');bytes.writeUInt32LE(bytes.length-8,4);bytes.write('WAVEfmt ',8);bytes.writeUInt32LE(16,16);bytes.writeUInt16LE(1,20);bytes.writeUInt16LE(2,22);bytes.writeUInt32LE(rate,24);bytes.writeUInt32LE(rate*4,28);bytes.writeUInt16LE(4,32);bytes.writeUInt16LE(16,34);bytes.write('data',36);bytes.writeUInt32LE(frames*4,40);
 for(let f=0;f<frames;f++){const sample=f%480===0?30000:Math.round(Math.sin(2*Math.PI*437.3*f/rate)*10000);bytes.writeInt16LE(sample,44+f*4);bytes.writeInt16LE(-sample,46+f*4);}
 const fixture=path.join(directory,'antiphase.wav');await writeFile(fixture,bytes);
 const child=spawn(process.env.PLUMDECK_TEST_HOST||path.resolve(import.meta.dirname,'../build-upstream/plumdeck-mixxx-engine-host'),[],{env:{...process.env,PLUMDECK_MIXXX_OUTPUT_DEVICE:process.env.PLUMDECK_MIXXX_OUTPUT_DEVICE||'BlackHole 2ch',PLUMDECK_WAVEFORM_CACHE:path.join(directory,'cache')}});
 let hello,id=0,stderr='';const pending=new Map(),points=[];
 child.stderr.on('data',data=>stderr=(stderr+data).slice(-4000));
 createInterface({input:child.stdout}).on('line',line=>{const m=JSON.parse(line);if(m.event==='deck.clock.v2')points.push(...m.data.points);if(m.kind!=='event')pending.get(m.id)?.(m);});
 const command=async(op,params={})=>{
  const current=++id;const response=new Promise((resolve,reject)=>{const timer=setTimeout(()=>reject(new Error(`${op}: ${stderr}`)),5000);pending.set(current,m=>{clearTimeout(timer);pending.delete(current);resolve(m);});});
  child.stdin.write(JSON.stringify({id:current,op,params,...(hello?{engineId:hello.engineId,sessionId:hello.sessionId}:{})})+'\n');
  const reply=await response;assert.notEqual(reply.kind,'error',JSON.stringify(reply));return reply.data??reply;
 };
 try{
  hello=await command('session.hello');
  let ready;for(let i=0;i<200;i++){ready=await command('state.snapshot');if(ready.audio.applied)break;await delay(10);}
  assert(ready.engine.capabilities.includes('deck.clock.v2'));
  const probe=await command('engine.clock.probe');assert(probe.sentNativeUs>=probe.receivedNativeUs);
  await command('deck.load',{deck:'A',track:{trackId:'antiphase',path:fixture}});
  let state;for(let i=0;i<200;i++){state=await command('state.snapshot');if(state.decks.A.track)break;await delay(10);}
  assert(state.decks.A.track);const generation=state.decks.A.loadGeneration;
  const ensure=await command('waveform.ensure',{deck:'A',loadGeneration:generation});assert(ensure.assetKey,JSON.stringify(ensure));
  let manifest;for(let i=0;i<300;i++){manifest=await command('waveform.manifest',{assetKey:ensure.assetKey});if(manifest.state==='ready'||manifest.state==='error')break;await delay(20);}
  assert.equal(manifest.state,'ready',JSON.stringify(manifest));assert.equal(manifest.sourceFrameCount,frames);assert.equal(manifest.sourceSampleRateHz,rate);
  let count=0,energy=0;
  for(let i=0;i<2;i++){
    const binary=await readFile(path.join(directory,'cache',ensure.assetKey,`0-${i}-bands.bin`));const tile=parseTile(binary.buffer.slice(binary.byteOffset,binary.byteOffset+binary.byteLength));
    for(let b=0;b<tile.bins;b++){assert.equal(tile.fields[0][b],-tile.fields[1][tile.bins+b]);count+=tile.counts[b];energy+=tile.fields[2][b]*tile.counts[b];}
  }
  const fullBytes=await readFile(path.join(directory,'cache',ensure.assetKey,'0-0-full.bin'));
  const full=parseTile(fullBytes.buffer.slice(fullBytes.byteOffset,fullBytes.byteOffset+fullBytes.byteLength));assert.equal(full.bands,false);assert(full.fields.slice(3).every(field=>field.every(value=>value===0)));
  const damaged=Buffer.from(fullBytes);damaged[100]^=1;await writeFile(path.join(directory,'cache',ensure.assetKey,'0-0-full.bin'),damaged);
  await command('waveform.invalidate',{assetKey:ensure.assetKey});
  for(let attempt=0;attempt<200;attempt++){const m=await command('waveform.manifest',{assetKey:ensure.assetKey});if(m.state==='ready')break;await delay(10);}
  const repaired=await readFile(path.join(directory,'cache',ensure.assetKey,'0-0-full.bin'));assert.deepEqual(repaired,fullBytes,'Corrupted immutable tile is reconstructed from the bound source');
  assert.equal(count,frames);let expected=0;for(let f=0;f<frames;f++)expected+=(bytes.readInt16LE(44+f*4)/32768)**2;
  assert(Math.abs(energy-expected)/expected<1e-6);
  const request={deck:'A',assetKey:ensure.assetKey,loadGeneration:generation,requestId:'pcm-test',startSourceFrame:479,endSourceFrame:1503,detail:'pcm',priority:0};
  let window;for(let i=0;i<100;i++){window=await command('waveform.requestRange',request);if(window.state==='ready')break;await delay(10);}
  assert.equal(window.state,'ready',JSON.stringify(window));
  const raw=await readFile(path.join(directory,'cache',ensure.assetKey,`pcm-${window.windowId}.bin`));
  const fine=parsePcmWindow(raw.buffer.slice(raw.byteOffset,raw.byteOffset+raw.byteLength),1);
  assert.equal(fine.startFrame,479);assert.equal(fine.bins,1024);
  for(let i=0;i<fine.bins;i++){assert.equal(fine.fields[0][i],bytes.readInt16LE(44+(479+i)*4)/32768);assert.equal(fine.fields[0][i+fine.bins],-fine.fields[0][i]);}
  assert.equal((await command('waveform.requestRange',{...request,loadGeneration:generation+1})).error,'STALE_ASSET');
  await command('waveform.cancelRequest',{requestId:'pcm-test'});
  await command('deck.play',{deck:'A'});await delay(350);
  const moving=points.map(parseClockPoint).filter(p=>p?.transportPlaying&&p.interpolationSafe&&p.sourceFrameStart>0);
  assert(moving.length>20);assert(moving.every(p=>p.sourceSampleRateHz===rate));
  for(const p of moving){assert(Math.abs(p.velocityRatioMean-1)<.03);assert.equal(p.outputFrames,256);assert.equal(p.timestampReference,'deck-postprocess-observed');}
  await appendFile(fixture,Buffer.from([0]));assert.equal((await command('waveform.ensure',{deck:'A',loadGeneration:generation})).error,'SOURCE_CHANGED');
  console.log(JSON.stringify({directory,frames,tiles:2,clockPoints:moving.length,decoder:manifest.decoderProvider}));
 }finally{child.stdin.end();await new Promise(resolve=>child.once('exit',resolve));}
});
