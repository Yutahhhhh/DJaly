import test from 'node:test';
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {createInterface} from 'node:readline';
import {mkdtemp,writeFile,readFile} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import path from 'node:path';
import {parseTile,parsePcmWindow} from '../../../src/services/waveform/protocol.ts';
import {parseClockPoint} from '../../../src/types/deck-performance.ts';
const delay=ms=>new Promise(r=>setTimeout(r,ms));
test('four-deck resampler callback budget at fractional, unity and high reverse rates', {timeout:60000},async()=>{
 const directory=await mkdtemp(path.join(tmpdir(),'plumdeck-clock-waveform-'));
 const rate=48000,frames=rate*60+3,bytes=Buffer.alloc(44+frames*4);
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
  const decks=['A','B','C','D'];
  for(const deck of decks.slice(1))await command('deck.load',{deck,track:{trackId:deck,path:fixture}});
  for(let attempt=0;attempt<300;attempt++){const s=await command('state.snapshot');if(decks.every(d=>s.decks[d].track))break;await delay(10);}
  const results=[];
  for(const speed of [.3,1,-6,-16]){
    for(const deck of decks){await command('deck.seek',{deck,positionMs:30000});await command('deck.scratch',{deck,phase:'begin',positionMs:0,gestureId:deck});}
    let displacement=0,baseline;
    for(let step=0;step<100;step++){
      displacement+=speed*20;for(const deck of decks)await command('deck.scratch',{deck,phase:'move',positionMs:displacement,gestureId:deck});
      if(step===20)baseline=await command('engine.audioHealth');
      await delay(20);
    }
    const health=await command('engine.audioHealth');const times=health.callbackDurationsUs.sort((a,b)=>a-b),p999=times[Math.ceil(times.length*.999)-1];
    assert.equal(health.lateCallbacks,baseline.lateCallbacks,'No callback deadline overruns after warmup');assert.equal(health.xruns,baseline.xruns,'No PortAudio xruns after warmup');assert(times.length>200);assert(p999<.75*256/44100*1e6,`Callback budget at ${speed}x: ${p999}us`);
    results.push({speed,samples:times.length,p999,max:times.at(-1),late:health.lateCallbacks});
    for(const deck of decks)await command('deck.scratch',{deck,phase:'end',positionMs:displacement,gestureId:deck});
  }
  console.log(JSON.stringify({directory,outputRate:44100,bufferFrames:256,decks:4,results}));
 }finally{child.stdin.end();await new Promise(resolve=>child.once('exit',resolve));}
});
