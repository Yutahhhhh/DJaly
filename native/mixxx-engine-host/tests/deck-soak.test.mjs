import test from 'node:test';
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {createInterface} from 'node:readline';
import {mkdtemp,writeFile} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import path from 'node:path';
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
  const asset=await command('waveform.ensure',{deck:'A',loadGeneration:generation});assert(asset.assetKey,JSON.stringify(asset));
  let manifest;for(let i=0;i<300;i++){manifest=await command('waveform.manifest',{assetKey:asset.assetKey});if(manifest.state==='ready'||manifest.state==='error')break;await delay(20);}
  assert.equal(manifest.state,'ready',JSON.stringify(manifest));
  await command('recording.start');await delay(1000);
  const baseline=await command('engine.audioHealth');const samples=new Float64Array(1000000);let count=0,cycle=-1,lastReport=0,finalHealth=baseline,maxUs=0,aboveBudget=0;
  const started=performance.now(),seconds=Number(process.env.DJALY_SOAK_SECONDS||60);assert(seconds>0&&seconds<=3600);
  while(performance.now()-started<seconds*1000){
    const nextCycle=Math.floor((performance.now()-started)/10000);
    if(nextCycle!==cycle){cycle=nextCycle;const speed=[.3,1,-6,-16][cycle%4];
      for(const deck of decks){await command('deck.loop.enable',{deck,enabled:false});await command('deck.seek',{deck,positionMs:30000});await command('deck.scratch',{deck,phase:'begin',positionMs:0,gestureId:deck});}
      for(let step=1;step<=5;step++){for(const deck of decks)await command('deck.scratch',{deck,phase:'move',positionMs:speed*step*20,gestureId:deck});await delay(20);}
      for(const deck of decks){await command('deck.scratch',{deck,phase:'end',positionMs:speed*100,gestureId:deck});await command('deck.loop.enable',{deck,enabled:true});}
    }
    await delay(850);const health=await command('engine.audioHealth');
    // Complete the requested observation period even if a deadline is missed;
    // retain the strict gates below rather than reporting a shortened run.
    finalHealth=health;
    for(const value of health.callbackDurationsUs){assert(count<samples.length);samples[count++]=value;maxUs=Math.max(maxUs,value);if(value>=.75*256/44100*1e6)aboveBudget++;}
    const state=await command('state.snapshot');assert(state.recording.active);assert(decks.every(deck=>!state.decks[deck].scratching&&state.decks[deck].status==='playing'));
    if(performance.now()-started-lastReport>=60000){lastReport=performance.now()-started;console.log(JSON.stringify({elapsedSeconds:Math.floor((performance.now()-started)/1000),callbacks:count,xruns:health.xruns-baseline.xruns,lateCallbacks:health.lateCallbacks-baseline.lateCallbacks,maxUs,aboveBudget}));}
  }
  await command('recording.stop');assert(count>0,'No audio callback durations were observed');const sorted=samples.subarray(0,count).sort();const p999=sorted[Math.ceil(count*.999)-1];
  console.log(JSON.stringify({directory,durationSeconds:seconds,callbacks:count,p999Us:p999,maxUs:sorted.at(-1),recording:true,decks:4,xruns:finalHealth.xruns-baseline.xruns,lateCallbacks:finalHealth.lateCallbacks-baseline.lateCallbacks,dropped:finalHealth.dropped-baseline.dropped}));
  await writeFile(path.join(directory,'callback-times.f64'),Buffer.from(samples.buffer,0,count*8));
  assert(p999<.75*256/44100*1e6,`Callback p99.9 ${p999}us exceeds the 4353.74us budget`);
  assert.equal(finalHealth.xruns,baseline.xruns,'No PortAudio xruns during soak');
  assert.equal(finalHealth.lateCallbacks,baseline.lateCallbacks,'No callback deadline overruns during soak');
  assert.equal(finalHealth.dropped,baseline.dropped,'No dropped callback measurements');
 }finally{child.stdin.end();await new Promise(resolve=>child.once('exit',resolve));}
});
