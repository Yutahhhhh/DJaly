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
test('four-deck recording and scratch soak with PortAudio xrun monitoring', {timeout:(Number(process.env.DJALY_SOAK_SECONDS||60)+60)*1000},async()=>{
 const directory=await mkdtemp(path.join(tmpdir(),'djaly-clock-waveform-'));
 const rate=48000,frames=rate*60+3,bytes=Buffer.alloc(44+frames*4);
 bytes.write('RIFF');bytes.writeUInt32LE(bytes.length-8,4);bytes.write('WAVEfmt ',8);bytes.writeUInt32LE(16,16);bytes.writeUInt16LE(1,20);bytes.writeUInt16LE(2,22);bytes.writeUInt32LE(rate,24);bytes.writeUInt32LE(rate*4,28);bytes.writeUInt16LE(4,32);bytes.writeUInt16LE(16,34);bytes.write('data',36);bytes.writeUInt32LE(frames*4,40);
 for(let f=0;f<frames;f++){const sample=f%480===0?30000:Math.round(Math.sin(2*Math.PI*437.3*f/rate)*10000);bytes.writeInt16LE(sample,44+f*4);bytes.writeInt16LE(-sample,46+f*4);}
 const fixture=path.join(directory,'antiphase.wav');await writeFile(fixture,bytes);
 const child=spawn(process.env.DJALY_TEST_HOST||path.resolve(import.meta.dirname,'../build-upstream/djaly-mixxx-engine-host'),[],{env:{...process.env,DJALY_MIXXX_OUTPUT_DEVICE:process.env.DJALY_MIXXX_OUTPUT_DEVICE||'BlackHole 2ch',DJALY_MIXXX_RECORDING_DIR:directory,DJALY_WAVEFORM_CACHE:path.join(directory,'cache')}});
 let hello,id=0,stderr='';const pending=new Map(),points=[];
 child.stderr.on('data',data=>stderr=(stderr+data).slice(-4000));
 createInterface({input:child.stdout}).on('line',line=>{const m=JSON.parse(line);if(m.kind!=='event')pending.get(m.id)?.(m);});
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
  for(const deck of decks){await command('deck.loop.set',{deck,startMs:10000,endMs:50000});await command('deck.loop.enable',{deck,enabled:true});await command('deck.play',{deck});}
  await command('waveform.ensure',{deck:'A',loadGeneration:generation});
  await command('recording.start');await delay(1000);
  const baseline=await command('engine.audioHealth');const samples=new Float64Array(1000000);let count=0,cycle=-1,lastReport=0;
  const started=performance.now(),seconds=Number(process.env.DJALY_SOAK_SECONDS||60);assert(seconds>0&&seconds<=3600);
  while(performance.now()-started<seconds*1000){
    const nextCycle=Math.floor((performance.now()-started)/10000);
    if(nextCycle!==cycle){cycle=nextCycle;const speed=[.3,1,-6,-16][cycle%4];
      for(const deck of decks){await command('deck.loop.enable',{deck,enabled:false});await command('deck.seek',{deck,positionMs:30000});await command('deck.scratch',{deck,phase:'begin',positionMs:0,gestureId:deck});}
      for(let step=1;step<=5;step++){for(const deck of decks)await command('deck.scratch',{deck,phase:'move',positionMs:speed*step*20,gestureId:deck});await delay(20);}
      for(const deck of decks){await command('deck.scratch',{deck,phase:'end',positionMs:speed*100,gestureId:deck});await command('deck.loop.enable',{deck,enabled:true});}
    }
    await delay(850);const health=await command('engine.audioHealth');
    assert.equal(health.xruns,baseline.xruns,'No PortAudio xruns during soak');assert.equal(health.lateCallbacks,baseline.lateCallbacks,'No callback deadline overruns during soak');
    for(const value of health.callbackDurationsUs){assert(count<samples.length);samples[count++]=value;}
    const state=await command('state.snapshot');assert(state.recording.active);assert(decks.every(deck=>!state.decks[deck].scratching&&state.decks[deck].status==='playing'));
    if(performance.now()-started-lastReport>=60000){lastReport=performance.now()-started;console.log(JSON.stringify({elapsedSeconds:Math.floor((performance.now()-started)/1000),callbacks:count,xruns:health.xruns-baseline.xruns}));}
  }
  await command('recording.stop');const sorted=samples.subarray(0,count).sort();const p999=sorted[Math.ceil(count*.999)-1];
  assert(p999<.75*256/44100*1e6);console.log(JSON.stringify({directory,durationSeconds:seconds,callbacks:count,p999Us:p999,maxUs:sorted.at(-1),recording:true,decks:4}));
 }finally{child.stdin.end();await new Promise(resolve=>child.once('exit',resolve));}
});
