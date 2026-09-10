// Checks the actual relocatable executable/DLL set even on CI with no audio device.
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { createInterface } from 'node:readline';
import { resolve, dirname, basename, join } from 'node:path';
import { cp, mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
const original=resolve(process.argv[2]);
const temporary=process.platform==='win32'?await mkdtemp(join(tmpdir(),'Plumdeck 移動 ')):null;
if(temporary) await cp(dirname(original),join(temporary,'engine'),{recursive:true});
const binary=temporary?join(temporary,'engine',basename(original)):original;
const env={...process.env};
if(process.platform==='win32') env.PATH=`${env.SystemRoot}\\System32;${env.SystemRoot}`;
const child=spawn(binary,[],{env,cwd:temporary||dirname(binary),windowsHide:true,stdio:['pipe','pipe','pipe']});
const exited=new Promise(resolve=>child.on('exit',resolve));
let diagnostics='', session, id=0;
const pending=new Map();
child.stderr.on('data',b=>{diagnostics=(diagnostics+b).slice(-8000)});
createInterface({input:child.stdout}).on('line',line=>{
    let value;try{value=JSON.parse(line)}catch{return}
    const callback=pending.get(value.id);
    if(callback){pending.delete(value.id);callback(value)}
});
function command(op){return new Promise((resolve,reject)=>{
    const key=++id;
    const timeout=setTimeout(()=>reject(new Error(`Host timed out: ${diagnostics}`)),20000);
    pending.set(key,value=>{clearTimeout(timeout);if(value.kind==='error')reject(new Error(JSON.stringify(value)));else resolve(value)});
    child.stdin.write(JSON.stringify({kind:'command',protocol:1,id:key,op,params:{},
        ...(session?{engineId:session.engineId,sessionId:session.sessionId}:{})})+'\n');
})}
try{
    session=await command('session.hello');
    assert.equal(session.engine.implementation,'mixxx');
    assert.equal(session.engine.simulated,false);
    const snapshot=await command('state.snapshot');
    assert(snapshot.data.decks.A && snapshot.data.decks.D);
    console.log('Relocated native engine: real Mixxx handshake and four-deck state passed');
}finally{
    child.stdin.end();const kill=setTimeout(()=>child.kill(),3000);
    await exited;clearTimeout(kill);
    if(temporary)await rm(temporary,{recursive:true,force:true});
}
