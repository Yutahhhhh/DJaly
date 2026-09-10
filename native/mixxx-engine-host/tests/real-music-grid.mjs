// Explicit local acceptance: node tests/real-music-grid.mjs /tmp/.../bundle.json
// The bundle is produced by backend/tests/real_music_grid_probe.py.
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {createInterface} from 'node:readline';
import {mkdtemp, readFile, writeFile} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import path from 'node:path';
import {parseTile,parsePcmWindow} from '../../../src/services/waveform/protocol.ts';
const bundle=JSON.parse(await readFile(process.argv[2], 'utf8'));
assert(bundle.length>0);
const directory=await mkdtemp(path.join(tmpdir(),'djaly-real-native-'));
const binary=process.env.DJALY_TEST_HOST||path.resolve(import.meta.dirname,'../build-upstream/djaly-mixxx-engine-host');
const child=spawn(binary,[],{env:{...process.env,DJALY_MIXXX_OUTPUT_DEVICE:process.env.DJALY_MIXXX_OUTPUT_DEVICE||'BlackHole 2ch',DJALY_WAVEFORM_CACHE:path.join(directory,'cache'),DJALY_MIXXX_RECORDING_DIR:directory}});
const delay=ms=>new Promise(r=>setTimeout(r,ms));
const pending=new Map(),events=[];let id=0,hello,stderr='';
child.stderr.on('data',data=>{stderr+=data;});
const exited=new Promise(resolve=>child.once('exit',(code,signal)=>resolve({code,signal})));
createInterface({input:child.stdout}).on('line',line=>{const m=JSON.parse(line);if(m.kind==='event')events.push(m);else pending.get(m.id)?.(m);});
async function command(op,params={},error){
 const current=++id;
 const response=new Promise((resolve,reject)=>{const timer=setTimeout(()=>{pending.delete(current);reject(Error(`timeout ${op}: ${stderr.slice(-1500)}`));},15000);pending.set(current,m=>{clearTimeout(timer);pending.delete(current);resolve(m);});});
 child.stdin.write(JSON.stringify({id:current,op,params,...(hello?{engineId:hello.engineId,sessionId:hello.sessionId}:{})})+'\n');
 const result=await response;
 if(error)assert.equal(result.error?.code,error,JSON.stringify(result));else assert.notEqual(result.kind,'error',JSON.stringify(result));
 return result.data??result;
}
async function until(predicate){for(let i=0;i<400;i++){const s=await command('state.snapshot');if(predicate(s))return s;await delay(25);}throw Error('State timeout');}
const gridParams=(deck,trackId,g)=>({deck,trackId,bpm:g.bpm,firstBeatMs:g.first_beat_ms,beatsPerBar:g.beats_per_bar,...(g.beat_times_ms?{beatTimesMs:g.beat_times_ms}:{}),...(g.beat_numbers?{beatNumbers:g.beat_numbers}:{})});
try{
 hello=await command('session.hello');
 const ready=await until(s=>s.audio.applied);
 assert(ready.engine.capabilities.includes('waveform.tiles.v2'));
 await command('recording.start');
 for(const [index,item] of bundle.entries()){
  const deck=['A','B','C','D'][index%4],trackId=String(item.id),g=item.metadata.beat_grid;
  await command('deck.load',{deck,track:{trackId,path:item.path,bpm:g.bpm,beatgridOffsetMs:g.first_beat_ms,beatsPerBar:g.beats_per_bar,...(g.beat_times_ms?{beatTimesMs:g.beat_times_ms}:{}),...(g.beat_numbers?{beatNumbers:g.beat_numbers}:{})}});
  let state=await until(s=>s.decks[deck].track?.trackId===trackId);
  const generation=state.decks[deck].loadGeneration;
  await command('deck.beatgrid.set',gridParams(deck,trackId,g));
  await command('deck.seek',{deck,positionMs:60000});
  await command('deck.play',{deck});
  await until(s=>s.decks[deck].positionMs>60100);
  const asset=await command('waveform.ensure',{deck,loadGeneration:generation});
  let manifest;
  for(let i=0;i<1200;i++){manifest=await command('waveform.manifest',{assetKey:asset.assetKey});if(manifest.state==='ready'||manifest.state==='error')break;await delay(50);}
  assert.equal(manifest.state,'ready',JSON.stringify(manifest));
  assert(manifest.sourceFrameCount>0);assert.equal(manifest.sourceSampleRateHz,Number(item.sampleRate));
  // Seeked detail and sequential analysis must use the same source-frame
  // origin, including compressed formats with decoder delay/priming.
  const start=Math.floor(60*manifest.sourceSampleRateHz/64)*64;
  const request={deck,assetKey:asset.assetKey,loadGeneration:generation,requestId:'real-pcm',startSourceFrame:start,endSourceFrame:start+512,detail:'pcm',priority:0};
  let window;
  for(let i=0;i<200;i++){window=await command('waveform.requestRange',request);if(window.state==='ready')break;await delay(25);}
  assert.equal(window.state,'ready',JSON.stringify(window));
  const parse=async(file,reader)=>{const bytes=await readFile(path.join(directory,'cache',asset.assetKey,file));return reader(bytes.buffer.slice(bytes.byteOffset,bytes.byteOffset+bytes.byteLength));};
  const fine=await parse(`pcm-${window.windowId}.bin`,buffer=>parsePcmWindow(buffer,64));
  const tileIndex=Math.floor(start/(64*2048));
  const coarse=await parse(`0-${tileIndex}-bands.bin`,parseTile);
  const bin=(start-coarse.startFrame)/64;
  for(let channel=0;channel<2;channel++)for(let i=0;i<fine.bins;i++)for(let field=0;field<3;field++){
    assert(Math.abs(fine.fields[field][channel*fine.bins+i]-coarse.fields[field][channel*coarse.bins+bin+i])<1e-5,`${item.codec}: PCM/tile source frame mismatch`);
  }
  await command('waveform.cancelRequest',{requestId:'real-pcm'});
  await command('deck.loop.set',{deck,startMs:60000,endMs:62000});
  await command('deck.loop.enable',{deck,enabled:true});await delay(2200);
  state=await command('state.snapshot');assert(state.decks[deck].positionMs<62400,'Loop did not wrap');
  await command('deck.loop.enable',{deck,enabled:false});
  const before=state.decks[deck].positionMs;
  const shifted={...g,first_beat_ms:g.first_beat_ms+5,beat_times_ms:g.beat_times_ms?.map(t=>t+5)};
  await command('deck.beatgrid.set',gridParams(deck,trackId,shifted));
  state=await command('state.snapshot');assert(state.decks[deck].positionMs>=before-10,'Grid edit sought backward');
  await command('deck.beatgrid.set',{...gridParams(deck,trackId,shifted),trackId:'obsolete'},'invalid_params');
  await command('deck.beatgrid.set',{...gridParams(deck,trackId,shifted),firstBeatMs:100,beatTimesMs:[100,100]},'invalid_params');
  await command('deck.scratch',{deck,phase:'begin',positionMs:0,gestureId:'real'});
  for(let i=1;i<=12;i++){await command('deck.scratch',{deck,phase:'move',positionMs:i<=6?i*6:72-i*6,gestureId:'real'});await delay(20);}
  await command('deck.scratch',{deck,phase:'end',positionMs:0,gestureId:'real'});
  await until(s=>!s.decks[deck].scratching&&s.decks[deck].status==='playing');
  await command('deck.pause',{deck});
  await command('deck.unload',{deck});
  await command('deck.load',{deck,track:{trackId,path:item.path,bpm:shifted.bpm,beatgridOffsetMs:shifted.first_beat_ms}});
  state=await until(s=>s.decks[deck].track?.trackId===trackId);
  assert(state.decks[deck].loadGeneration>generation);
  await command('deck.beatgrid.set',gridParams(deck,trackId,shifted));
  console.log(JSON.stringify({codec:item.codec,sha256:item.sha256,generation:state.decks[deck].loadGeneration,frames:manifest.sourceFrameCount,gridReload:true,scratch:true,loop:true}));
 }
 await command('recording.stop');
 assert(!events.some(e=>e.event==='deck.error'),JSON.stringify(events.filter(e=>e.event==='deck.error')));
 console.log(JSON.stringify({passed:bundle.length,directory,binary}));
}finally{
 child.stdin.end();const result=await Promise.race([exited,delay(5000).then(()=>null)]);if(!result)child.kill('SIGTERM');
 await writeFile(path.join(directory,'stderr.log'),stderr);
 assert.equal(result?.code,0,stderr.slice(-2000));
}
