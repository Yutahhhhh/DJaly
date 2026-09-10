import test from 'node:test';import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';import {createInterface} from 'node:readline';import net from 'node:net';
import {mkdtemp,writeFile} from 'node:fs/promises';import {tmpdir} from 'node:os';import path from 'node:path';
const delay=ms=>new Promise(resolve=>setTimeout(resolve,ms));
const tone=async(prefix)=>{
 const dir=await mkdtemp(path.join(tmpdir(),prefix));const sampleRate=44100,frames=sampleRate*10,wave=Buffer.alloc(44+frames*4);
 wave.write('RIFF');wave.writeUInt32LE(wave.length-8,4);wave.write('WAVEfmt ',8);wave.writeUInt32LE(16,16);wave.writeUInt16LE(1,20);wave.writeUInt16LE(2,22);wave.writeUInt32LE(sampleRate,24);wave.writeUInt32LE(sampleRate*4,28);wave.writeUInt16LE(4,32);wave.writeUInt16LE(16,34);wave.write('data',36);wave.writeUInt32LE(frames*4,40);
 for(let f=0;f<frames;f++){const v=Math.round(8000*Math.sin(f*.1));wave.writeInt16LE(v,44+f*4);wave.writeInt16LE(v,46+f*4);}const file=path.join(dir,'tone.wav');await writeFile(file,wave);return file;
};
test('native performance channel owns MIDI edges, faders, release and disconnect without a WebView',{timeout:15000},async()=>{
 const file=await tone('plumdeck-native-input-');
 const child=spawn(process.env.PLUMDECK_TEST_HOST||path.resolve(import.meta.dirname,'../build-upstream/plumdeck-mixxx-engine-host'),[],{env:{...process.env,PLUMDECK_MIXXX_OUTPUT_DEVICE:process.env.PLUMDECK_MIXXX_OUTPUT_DEVICE||'BlackHole 2ch'}});
 let hello,id=0,stderr='',socket;const pending=new Map(),capturedBySeq=new Map(),applied=new Map();child.stderr.on('data',b=>stderr=(stderr+b).slice(-3000));
 createInterface({input:child.stdout}).on('line',line=>{const m=JSON.parse(line);if(m.event==='deck.clock.v2')for(const p of m.data.points)if(p.deck==='A'&&p.inputOrigin==='native-midi'&&!applied.has(p.appliedInputSeq))applied.set(p.appliedInputSeq,p.nativeMonoUs);if(m.kind!=='event')pending.get(m.id)?.(m);});
 const command=async(op,params={})=>{const key=++id;const promise=new Promise((resolve,reject)=>{const timeout=setTimeout(()=>reject(new Error(stderr)),3000);pending.set(key,m=>{clearTimeout(timeout);pending.delete(key);resolve(m);});});child.stdin.write(JSON.stringify({id:key,op,params,...(hello?{engineId:hello.engineId,sessionId:hello.sessionId}:{})})+'\n');const reply=await promise;assert.notEqual(reply.kind,'error',JSON.stringify(reply));return reply.data??reply;};
 const until=async(predicate)=>{for(let i=0;i<200;i++){const s=await command('state.snapshot');if(predicate(s))return s;await delay(10);}throw new Error('state timeout '+JSON.stringify(await command('performance.endpoint'))+' '+JSON.stringify((await command('state.snapshot')).decks.A));};
 try{
  hello=await command('session.hello');await until(s=>s.audio.applied);await command('deck.load',{deck:'A',track:{trackId:'input',path:file}});const state=await until(s=>s.decks.A.track);await command('deck.seek',{deck:'A',positionMs:5000});
  const endpoint=await command('performance.endpoint');socket=net.createConnection(endpoint.path);await new Promise(resolve=>socket.once('connect',resolve));
  let observation;createInterface({input:socket}).on('line',line=>{observation=JSON.parse(line);});socket.write(JSON.stringify({token:endpoint.token,sensitivity:.1,ranges:[16,16,16,16],cues:[0,0,0,0]})+'\n');
  while(!observation)await delay(5);let seq=0;
  const t0=performance.now(),probe=await command('engine.clock.probe'),t3=performance.now();const clockOffset=(probe.receivedNativeUs+probe.sentNativeUs)/2-(t0+t3)*500;const uncertaintyUs=(t3-t0)*500;
  const send=(bytes)=>{const row=Buffer.alloc(48);row.writeBigUInt64LE(BigInt(++seq));row.writeBigUInt64LE(BigInt(Math.round(performance.now()*1000+clockOffset)),8);row.writeUInt32LE(state.decks.A.loadGeneration,16);capturedBySeq.set(seq,Number(row.readBigUInt64LE(8)));row[32]=bytes.length;Buffer.from(bytes).copy(row,33);socket.write(row);};
  send([0x90,0x36,127]);await until(s=>s.decks.A.scratching);
  for(let i=0;i<20;i++){send([0xb0,0x22,54]);await delay(10);}assert((await command('state.snapshot')).decks.A.positionMs<4990);
  await delay(30);const latencies=[...applied].filter(([seq])=>seq>1&&capturedBySeq.has(seq)).map(([seq,at])=>at-capturedBySeq.get(seq)).sort((a,b)=>a-b);
  assert(latencies.length>=15);assert(latencies.at(-1)<=2*256/44100*1e6+2000+uncertaintyUs);console.log(JSON.stringify({nativeInput:{samples:latencies.length,p99Us:latencies.at(-1),clockUncertaintyUs:uncertaintyUs}}));
  send([0x90,0x36,0]);await until(s=>!s.decks.A.scratching);
  send([0xb6,31,127]);send([0xb6,63,127]);await until(s=>s.mixer.crossfader===1);
  send([0x90,0x0b,127]);await until(s=>s.decks.A.status==='playing');send([0x90,0x0b,0]);
  send([0x90,0x36,127]);await until(s=>s.decks.A.scratching);socket.destroy();await until(s=>!s.decks.A.scratching);
 }finally{socket?.destroy();child.stdin.end();await new Promise(resolve=>child.once('exit',resolve));}
});

// ネイティブ演奏入力と RPC のポインタ操作は同じデッキを共有する。遅れて届いた
// 片方の解放が、もう片方の新しいジェスチャーを止めないことを実エンジンで確認する。
test('scratch ownership survives crossed native and control gestures',{timeout:30000},async()=>{
 const file=await tone('plumdeck-scratch-owner-');
 const child=spawn(process.env.PLUMDECK_TEST_HOST||path.resolve(import.meta.dirname,'../build-upstream/plumdeck-mixxx-engine-host'),[],{env:{...process.env,PLUMDECK_MIXXX_OUTPUT_DEVICE:process.env.PLUMDECK_MIXXX_OUTPUT_DEVICE||'BlackHole 2ch'}});
 let hello,id=0,stderr='',socket;const pending=new Map();child.stderr.on('data',b=>stderr=(stderr+b).slice(-3000));
 createInterface({input:child.stdout}).on('line',line=>{const m=JSON.parse(line);if(m.kind!=='event')pending.get(m.id)?.(m);});
 const command=async(op,params={})=>{const key=++id;const promise=new Promise((resolve,reject)=>{const timeout=setTimeout(()=>reject(new Error(stderr)),3000);pending.set(key,m=>{clearTimeout(timeout);pending.delete(key);resolve(m);});});child.stdin.write(JSON.stringify({id:key,op,params,...(hello?{engineId:hello.engineId,sessionId:hello.sessionId}:{})})+'\n');const reply=await promise;assert.notEqual(reply.kind,'error',JSON.stringify(reply));return reply.data??reply;};
 const until=async(predicate)=>{for(let i=0;i<200;i++){const s=await command('state.snapshot');if(predicate(s))return s;await delay(10);}throw new Error('state timeout '+JSON.stringify((await command('state.snapshot')).decks.A));};
 const scratching=async()=>(await command('state.snapshot')).decks.A.scratching;
 try{
  hello=await command('session.hello');await until(s=>s.audio.applied);
  await command('deck.load',{deck:'A',track:{trackId:'owner',path:file}});const state=await until(s=>s.decks.A.track);await command('deck.seek',{deck:'A',positionMs:5000});
  const endpoint=await command('performance.endpoint');socket=net.createConnection(endpoint.path);await new Promise(resolve=>socket.once('connect',resolve));
  let observation;createInterface({input:socket}).on('line',line=>{observation=JSON.parse(line);});socket.write(JSON.stringify({token:endpoint.token,sensitivity:.1,ranges:[16,16,16,16],cues:[0,0,0,0]})+'\n');
  while(!observation)await delay(5);let seq=0;
  const probe=await command('engine.clock.probe'),clockOffset=(probe.receivedNativeUs+probe.sentNativeUs)/2-performance.now()*1000;
  const send=(bytes)=>{const row=Buffer.alloc(48);row.writeBigUInt64LE(BigInt(++seq));row.writeBigUInt64LE(BigInt(Math.round(performance.now()*1000+clockOffset)),8);row.writeUInt32LE(state.decks.A.loadGeneration,16);row[32]=bytes.length;Buffer.from(bytes).copy(row,33);socket.write(row);};
  const web=(gestureId,phase,positionMs=0)=>command('deck.scratch',{deck:'A',gestureId,phase,positionMs});

  // 1. ポインタが先に握ったデッキをネイティブの begin が引き継ぐ。遅れて届いた
  //    ポインタの end はネイティブのジェスチャーを止めない。
  assert.equal((await web('web-1','begin')).accepted,true);await until(s=>s.decks.A.scratching);
  send([0x90,0x36,127]);await delay(60);
  await web('web-1','end');await delay(60);
  assert.equal(await scratching(),true,'stale control end stopped the newer native gesture');
  send([0x90,0x36,0]);await until(s=>!s.decks.A.scratching);

  // 2. 逆向き。ネイティブの touch OFF が新しいポインタのジェスチャーを止めない。
  send([0x90,0x36,127]);await until(s=>s.decks.A.scratching);
  assert.equal((await web('web-2','begin')).accepted,true);await delay(60);
  send([0x90,0x36,0]);await delay(60);
  assert.equal(await scratching(),true,'stale native end stopped the newer control gesture');
  await web('web-2','end');await until(s=>!s.decks.A.scratching);

  // A displaced native owner must not resume when the replacing pointer ends.
  send([0x90,0x36,127]);await until(s=>s.decks.A.scratching);
  await web('web-finished','begin');await web('web-finished','end');
  await until(s=>!s.decks.A.scratching);
  send([0xb0,0x22,65]);await delay(100);
  assert.equal(await scratching(),false,'old native move reacquired an idle deck without begin');
  send([0x90,0x36,0]);

  // 3. ホスト側 1.5 秒の古いジェスチャー watchdog も、ネイティブの継続を切らない。
  assert.equal((await web('web-3','begin')).accepted,true);await until(s=>s.decks.A.scratching);
  send([0x90,0x36,127]);
  for(let i=0;i<9;i++){send([0xb0,0x22,65]);await delay(200);}
  assert.equal(await scratching(),true,'control watchdog aborted a live native gesture');

  // 4. ロード世代の変化はどちらの所有でも必ず解放する。
  await command('deck.load',{deck:'A',track:{trackId:'owner-2',path:file}});
  await until(s=>!s.decks.A.scratching);
 }finally{socket?.destroy();child.stdin.end();await new Promise(resolve=>child.once('exit',resolve));}
});
