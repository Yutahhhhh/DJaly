import type { WaveformTile } from './protocol';
/** Bounded visible-bin traversal. Peak outlines and genuine PCM RMS remain separate. */
export function drawWaveformTiles(ctx:CanvasRenderingContext2D,tiles:WaveformTile[],startMs:number,spanMs:number,width:number,height:number,vertical:boolean,side:'left'|'right'){
  const length=vertical?height:width,breadth=vertical?width:height;
  const axis=vertical?(side==='left'?width-2:2):height/2;
  const scale=(breadth-12)*(vertical?1:.5),direction=vertical&&side==='right'?1:-1;
  for(const tile of tiles){
    if(tile.framesPerBin===1 && spanMs*tile.sampleRate/1000<=length){
      ctx.strokeStyle='#d6e6fa';ctx.lineWidth=1;
      for(let c=0;c<tile.channels;c++){
        ctx.beginPath();let started=false;
        for(let b=0;b<tile.bins;b++){
          const at=((tile.startFrame+b)/tile.sampleRate*1000-startMs)/spanMs*length;if(at<-2||at>length+2)continue;
          const center=(c+.5)*breadth/tile.channels;
          const amplitude=tile.fields[0][c*tile.bins+b]*(breadth/tile.channels-8)/2;
          const x=vertical?center-amplitude:at,y=vertical?at:center-amplitude;
          if(started)ctx.lineTo(x,y);else{ctx.moveTo(x,y);started=true;}
        }ctx.stroke();
      }continue;
    }
    const unit=tile.framesPerBin/tile.sampleRate*1000/spanMs*length;
    for(let b=0;b<tile.bins;b++){
      const at=((tile.startFrame+b*tile.framesPerBin)/tile.sampleRate*1000-startMs)/spanMs*length;
      if(at+unit<0||at>length)continue;
      let min=Infinity,max=-Infinity,energy=0,low=0,mid=0,high=0;
      for(let c=0;c<tile.channels;c++){const i=c*tile.bins+b;min=Math.min(min,tile.fields[0][i]);max=Math.max(max,tile.fields[1][i]);energy+=tile.fields[2][i];low+=tile.fields[3][i];mid+=tile.fields[4][i];high+=tile.fields[5][i];}
      const peak=Math.max(Math.abs(min),Math.abs(max)),rms=Math.sqrt(energy/tile.channels);
      const partialUnit=unit*tile.counts[b]/tile.framesPerBin;
      const rect=(amplitude:number)=>{const size=Math.min(1,amplitude)*scale;if(vertical)ctx.fillRect(Math.min(axis,axis+direction*size),at,size,partialUnit+.1);else ctx.fillRect(at,axis-size,partialUnit+.1,size*2);};
      ctx.fillStyle='#b8c8dd';rect(peak);
      const sum=low+mid+high;
      ctx.fillStyle=tile.bands&&sum>0?`rgb(${Math.round((26*low+255*mid+233*high)/sum)} ${Math.round((123*low+160*mid+241*high)/sum)} ${Math.round((240*low+44*mid+255*high)/sum)})`:'#e9f1ff';rect(rms);
    }
  }
}
