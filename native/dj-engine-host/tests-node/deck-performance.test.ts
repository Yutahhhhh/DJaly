import test from 'node:test';
import assert from 'node:assert/strict';
import { ClockMapping, presentPoint } from '../../../src/services/dj-engine/transport-clock.ts';
import { parseClockPoint, type DeckClockPoint } from '../../../src/types/deck-performance.ts';
import { createPresentationScheduler } from '../../../src/components/play/presentation-scheduler.ts';
import { parseTile, crc32, chooseLod } from '../../../src/services/waveform/protocol.ts';
const point:DeckClockPoint={schema:2,engineEpoch:'host',audioConfigEpoch:1,deck:'A',loadGeneration:2,trajectoryEpoch:3,sequence:4,outputFrameEnd:256,outputFrames:256,outputSampleRateHz:44100,sourceFrameStart:10000,sourceFrameEnd:10256,sourceSampleRateHz:48000,nativeMonoUs:1e6,timestampReference:'deck-postprocess-observed',velocityRatioMean:1,velocityRatioEnd:null,transportPlaying:true,scratching:false,appliedInputSeq:0,discontinuity:null,interpolationSafe:true};
test('clock domains retain RTT uncertainty, expire after suspend, reject invalid probes',()=>{
 const mapping=new ClockMapping();assert.equal(mapping.probe(100,1101000,1101000,102),true);
 assert.deepEqual(mapping.at(103),{nativeUs:1103000,uncertaintyUs:1000});
 assert.equal(mapping.probe(10,0,1,9),false);assert.equal(mapping.at(130000),null);
});
test('source rate, reverse, scratch horizon and explicit loop boundary',()=>{
 assert.equal(presentPoint(point,1010000).sourceFrame,10736);
 assert.equal(presentPoint({...point,velocityRatioMean:-6,scratching:true},1100000).sourceFrame,6800);
 assert.equal(presentPoint({...point,discontinuity:'loop-wrap',interpolationSafe:false},1010000).sourceFrame,10256);
 assert.equal(presentPoint(point,2000000).confidence,'stale');
 assert.equal(parseClockPoint({...point,outputFrameEnd:Number.MAX_SAFE_INTEGER+1}),null);
 assert.equal(parseClockPoint({...point,sourceFrameEnd:-48})?.sourceFrameEnd,-48);
});
test('workspace schedules one frame and preserves invalidation during draw',()=>{
 const frames:FrameRequestCallback[]=[];const scheduler=createPresentationScheduler(f=>{frames.push(f);return frames.length;},()=>{});
 let calls=0;scheduler.request(()=>{calls++;scheduler.request(()=>calls++);});scheduler.request(()=>calls++);
 assert.equal(frames.length,1);frames.shift()!(0);assert.equal(calls,2);assert.equal(frames.length,1);frames.shift()!(16);assert.equal(calls,3);
});
function tile(){
 const bytes=new ArrayBuffer(64+52*2),v=new DataView(bytes),u32=(o:number,n:number)=>v.setUint32(o,n,true);
 v.setUint32(0,0x444a5756);v.setUint16(4,2,true);v.setUint16(6,64,true);v.setUint16(12,2,true);u32(8,1);u32(16,2);u32(20,64);v.setBigUint64(32,67n,true);u32(40,48000);u32(44,104);u32(52,6);u32(64,64);u32(68,3);
 const values=[-1,0,-.5,0, 1,.25,.5,.125, .5,.01,.125,.005, .1,0,.1,0, .2,0,.2,0, .2,0,.2,0];
 values.forEach((n,i)=>v.setFloat32(72+i*4,n,true));u32(48,crc32(new Uint8Array(bytes,64)));return bytes;
}
test('binary tile decodes stereo and partial final bin; rejects corruption and hostile headers',()=>{
 const bytes=tile(),parsed=parseTile(bytes);assert.equal(parsed.coveredFrames,67);assert.deepEqual([...parsed.counts],[64,3]);assert.equal(parsed.fields[0][0],-1);
 new Uint8Array(bytes)[80]^=1;assert.throws(()=>parseTile(bytes));
 const huge=tile();new DataView(huge).setUint32(16,0xffffffff,true);assert.throws(()=>parseTile(huge));
 assert.equal(chooseLod(128),1);assert.equal(chooseLod(.5),0);
});
