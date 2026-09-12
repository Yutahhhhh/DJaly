import { djEngineClient } from '../dj-engine/client';
import { tileWorker } from "./worker-client";
import { invoke } from '@tauri-apps/api/core';
import { type WaveformTile } from './protocol';
import { normalizeWaveformManifest as normalizeManifest } from './manifest';
export { normalizeTileRanges } from './manifest';
export interface WaveformManifest {
  schemaVersion:2; assetKey:string; sourceSampleRateHz:number; channelCount:1|2;
  sourceFrameOrigin:number; sourceFrameCount:number; frameCountFinal:boolean;
  baseFramesPerBin:64; tileBins:2048; state:'queued'|'partial'|'ready'|'error';revision:number;
  levels:{lod:number;framesPerBin:number;readyTileRanges:[number,number][];bandReadyTileRanges:[number,number][]}[];
}
export function normalizeWaveformManifest(value: unknown): WaveformManifest | null {
  return normalizeManifest(value) as WaveformManifest | null;
}

const LIMIT=64*1024*1024;
type Entry={promise:Promise<WaveformTile>;bytes:number;refs:number;used:number;tile?:WaveformTile};
class WaveformRepository {
  private entries=new Map<string,Entry>();
  private bytes=0;
  private active=0;
  private waiting:{start:()=>void;priority:number;entry:Entry;cancel:()=>void}[]=[];
  acquire(session:string,assetKey:string,lod:number,tileIndex:number,priority=1,origin=0){
    const key=`${session}:${assetKey}:${lod}:${tileIndex}:bands`;
    let entry=this.entries.get(key);
    if(!entry){
      let resolve!:(tile:WaveformTile)=>void,reject!:(error:unknown)=>void;
      const promise=new Promise<WaveformTile>((ok,fail)=>{resolve=ok;reject=fail;});
      entry={promise,bytes:0,refs:0,used:performance.now()};this.entries.set(key,entry);
      const target=entry;
      const start=()=>{
        this.active++;
        void invoke<ArrayBuffer>('dj_waveform_tile',{sessionId:session,assetKey,lod,tileIndex,variant:'bands'}).then(async buffer=>{
          const byteLength=buffer.byteLength;
          const tile=await tileWorker.parse(buffer);
          if(tile.lod!==lod||tile.startFrame!==origin+tileIndex*2048*tile.framesPerBin)throw new Error('Waveform range mismatch');
          this.prune(byteLength);
          if(this.bytes+byteLength>LIMIT)throw new Error("Waveform memory budget reached");
          target.tile=tile;target.bytes=byteLength;this.bytes+=target.bytes;resolve(tile);
        }).catch(error=>{this.entries.delete(key);if(error instanceof Error&&/Invalid waveform|range mismatch/.test(error.message))void djEngineClient.send("waveform.invalidate",{assetKey}).catch(()=>{});reject(error);}).finally(()=>{this.active--;this.pump();});
      };
      this.waiting.push({start,priority,entry:target,cancel:()=>{this.entries.delete(key);reject(new Error("Waveform request cancelled"));}});
    }
    const queued=this.waiting.find(item=>item.entry===entry);if(queued)queued.priority=Math.min(queued.priority,priority);
    entry.refs++;entry.used=performance.now();this.pump();
    let released=false;
    return {promise:entry.promise,release:()=>{if(released)return;released=true;entry!.refs--;if(!entry!.refs){const index=this.waiting.findIndex(item=>item.entry===entry);if(index>=0)this.waiting.splice(index,1)[0].cancel();}this.prune();}};
  }
  private pump(){
    this.waiting.sort((a,b)=>a.priority-b.priority);
    while(this.active<2&&this.waiting.length)this.waiting.shift()!.start();
  }
  private prune(incoming=0){
    if(this.bytes+incoming<=LIMIT)return;
    for(const [key,entry] of [...this.entries].sort((a,b)=>a[1].used-b[1].used)){
      if(entry.refs||!entry.bytes)continue;this.entries.delete(key);this.bytes-=entry.bytes;if(this.bytes+incoming<=LIMIT)break;
    }
  }
}
export const waveformRepository=new WaveformRepository();
