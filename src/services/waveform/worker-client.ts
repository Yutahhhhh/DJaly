import { parseTile, parsePcmWindow, type WaveformTile } from './protocol';
class TileWorker {
  private worker:Worker|null=null;
  private disabled=false;
  private sequence=0;
  private pending=new Map<number,{resolve:(tile:WaveformTile)=>void;reject:(error:unknown)=>void;timer:ReturnType<typeof setTimeout>}>();
  parse(buffer:ArrayBuffer,pcmBin?:number):Promise<WaveformTile>{
    if(!this.worker&&!this.disabled){
      try{
        this.worker=new Worker(new URL('./worker.ts',import.meta.url),{type:'module'});
        this.worker.onmessage=({data})=>{const item=this.pending.get(data.id);if(!item)return;this.pending.delete(data.id);clearTimeout(item.timer);if(data.error)item.reject(new Error(data.error));else item.resolve(data.tile);};
        this.worker.onerror=()=>this.fail();
      }catch{this.disabled=true;}
    }
    if(!this.worker)return new Promise((resolve,reject)=>setTimeout(()=>{try{resolve(pcmBin?parsePcmWindow(buffer,pcmBin):parseTile(buffer));}catch(error){reject(error);}},0));
    const id=++this.sequence;
    return new Promise((resolve,reject)=>{
      const timer=setTimeout(()=>this.fail(),5000);
      this.pending.set(id,{resolve,reject,timer});
      try{this.worker!.postMessage({id,buffer,pcmBin},[buffer]);}catch{this.fail();}
    });
  }
  private fail(){this.worker?.terminate();this.worker=null;this.disabled=true;for(const item of this.pending.values()){clearTimeout(item.timer);item.reject(new Error('Waveform worker unavailable'));}this.pending.clear();}
}
export const tileWorker=new TileWorker();
