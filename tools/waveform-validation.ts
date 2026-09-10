// 実 WKWebView 上で共有 renderer を長時間動かすだけの検証ページ。ユーザーの
// ライブラリや音声デバイスには一切触れない。合成タイルを 4 面 (1200px / DPR2)
// へ描き続け、rAF 間隔と描画時間の分布を WAVEFORM_VALIDATION として返す。
// rAF 間隔は「描画要求が返ってきた間隔」であり、実際に表示された時刻ではない。
import {waveformRenderer} from '../src/services/waveform/renderer';
import type {WaveformTile} from '../src/services/waveform/protocol';

const params=new URLSearchParams(location.search);
const seconds=Math.min(Math.max(Number(params.get('seconds')||600),5),7200);
const surfaceCount=Math.min(Math.max(Number(params.get('surfaces')||4),1),8);
const cssWidth=Number(params.get('width')||1200),cssHeight=Number(params.get('height')||96),scale=2;
const status=document.getElementById('status')!,host=document.getElementById('surfaces')!;
const post=(line:string)=>{
  (window as unknown as {ipc?:{postMessage(value:string):void}}).ipc?.postMessage(line);
  console.log(line);
};
const report=(payload:unknown)=>{const line='WAVEFORM_VALIDATION '+JSON.stringify(payload);status.textContent=line;post(line);};
// ハーネス側で「ページが動いていない」と「ipcが届かない」を区別できるようにする。
window.addEventListener('error',event=>post('VALIDATION_ERROR '+(event.error?.stack||event.message)));
window.addEventListener('unhandledrejection',event=>post('VALIDATION_ERROR '+String(event.reason)));
// Bundle this page for acceptance so development HMR cannot restart it.
post('VALIDATION_PROGRESS {"stage":"loaded"}');

const rate=48000,bins=2048,framesPerBin=64,tileCount=16;
const tile=(index:number):WaveformTile=>{
  const counts=new Uint32Array(bins).fill(framesPerBin);
  const fields=Array.from({length:6},()=>new Float32Array(bins*2));
  for(let channel=0;channel<2;channel++)for(let bin=0;bin<bins;bin++){
    const at=channel*bins+bin,phase=(index*bins+bin)*.017;
    const peak=Math.min(.98,.2+.55*Math.abs(Math.sin(phase))+(bin%512===0?.3:0));
    fields[0][at]=-peak;fields[1][at]=peak;fields[2][at]=peak*peak*.45;
    fields[3][at]=fields[2][at]*(1-bin/bins);fields[4][at]=fields[2][at]*.25;fields[5][at]=fields[2][at]*bin/bins;
  }
  return {lod:0,channels:2,bins,framesPerBin,startFrame:index*bins*framesPerBin,coveredFrames:bins*framesPerBin,sampleRate:rate,bands:true,counts,fields};
};
const tiles=Array.from({length:tileCount},(_,index)=>tile(index));
const tileMs=bins*framesPerBin/rate*1000,totalMs=tileMs*tileCount,spanMs=tileMs*1.25;

const surfaces=Array.from({length:surfaceCount},()=>{
  const canvas=document.createElement('canvas');
  canvas.width=cssWidth*scale;canvas.height=cssHeight*scale;
  canvas.style.width=`${cssWidth}px`;canvas.style.height=`${cssHeight}px`;
  host.append(canvas);
  const ctx=canvas.getContext('2d')!;ctx.scale(scale,scale);return ctx;
});

// Warm every tile before timing; first-seen uploads are measured separately by
// the renderer regression, not counted as steady-state scrolling work.
for(const tile of tiles)waveformRenderer.draw(surfaces[0],[tile],tile.startFrame/rate*1000,spanMs,cssWidth,cssHeight,false,'left');

const quantile=(sorted:number[],q:number)=>sorted.length?sorted[Math.min(sorted.length-1,Math.ceil(sorted.length*q)-1)]:0;
const summary=(values:number[])=>{
  const sorted=[...values].sort((a,b)=>a-b);
  return {count:sorted.length,p50:quantile(sorted,.5),p95:quantile(sorted,.95),p99:quantile(sorted,.99),max:sorted.at(-1)??0};
};

const wallStart=Date.now();let lastFrameAt=Date.now(),stalls=0,finished=false;
const intervals:number[]=[],draws:number[]=[],minutes:{minute:number;frames:number;intervalP99Ms:number;drawP99Ms:number;gpuBytes:number}[]=[];
let previous=0,started=0,minuteIntervals:number[]=[],minuteDraws:number[]=[],minute=0,visibleTiles=0;

const frame=(now:number)=>{
  if(!started){started=previous=now;post('VALIDATION_PROGRESS {"stage":"first-frame"}');requestAnimationFrame(frame);return;}
  const interval=now-previous;previous=now;intervals.push(interval);
  // 曲全体をゆっくり流し、タイルの出入りと GPU geometry の再利用を継続的に起こす。
  const startMs=(now-started)/1000%(totalMs/1000-spanMs/1000)*1000;
  const visible=tiles.filter(t=>{
    const from=t.startFrame/rate*1000;return from+tileMs>startMs&&from<startMs+spanMs;
  });
  visibleTiles=visible.length;
  const drawStart=performance.now();
  for(let index=0;index<surfaces.length;index++){
    const ctx=surfaces[index];
    ctx.clearRect(0,0,cssWidth,cssHeight);
    waveformRenderer.draw(ctx,visible,startMs,spanMs,cssWidth,cssHeight,false,index%2?'right':'left');
  }
  const drawMs=performance.now()-drawStart;
  draws.push(drawMs);minuteIntervals.push(interval);minuteDraws.push(drawMs);

  const elapsed=(now-started)/1000;
  if(elapsed>=(minute+1)*60){
    minutes.push({minute:++minute,frames:minuteIntervals.length,intervalP99Ms:summary(minuteIntervals).p99,drawP99Ms:summary(minuteDraws).p99,gpuBytes:waveformRenderer.diagnostics.gpuBytes});
    minuteIntervals=[];minuteDraws=[];
    status.textContent=`elapsed ${Math.round(elapsed)}s / ${seconds}s frames ${intervals.length}`;
    post('VALIDATION_PROGRESS '+JSON.stringify(minutes.at(-1)));
  }
  lastFrameAt=Date.now();
  if(elapsed<seconds&&!finished){requestAnimationFrame(frame);return;}
  if(finished)return;
  finish(false);
};
// rAF が止められた状態の数字を「良い結果」と取り違えないための番人。
// 実時間が想定の 1.5 倍を超えたら、throttled として必ず結果を返して終わる。
setInterval(()=>{
  if(finished)return;
  if(Date.now()-lastFrameAt>3000)stalls++;
  if(Date.now()-wallStart>seconds*1500)finish(true);
},1000);
function finish(throttled:boolean){
  if(finished)return;finished=true;
  const elapsed=intervals.length?(previous-started)/1000:0;
  const warmIntervals = intervals.slice(120), warmDraws = draws.slice(120);
  const period = summary(warmIntervals).p50;
  const missed = warmIntervals.reduce((sum, value) => sum + Math.max(0, Math.round(value / period) - 1), 0);
  const missedRatio = missed / (warmIntervals.length + missed);
  const gates = {
    completed: !throttled && elapsed >= seconds && stalls === 0,
    refresh: period > 0 && period <= 20,
    cpu: summary(warmDraws).p99 <= period * .5,
    continuity: missedRatio <= .005,
    gpuBudget: waveformRenderer.diagnostics.gpuBytes <= 32 * 1024 * 1024 && waveformRenderer.diagnostics.rasterBytes <= 32 * 1024 * 1024,
  };
  report({
    passed:Object.values(gates).every(Boolean),gates,periodMs:period,missedRatio,durationSeconds:Math.round(elapsed),surfaces:surfaces.length,cssWidth,cssHeight,backingScale:scale,
    devicePixelRatio:globalThis.devicePixelRatio,frames:intervals.length,meanFps:intervals.length/elapsed,
    rafIntervalMs:summary(intervals.slice(1)),drawMsPerFrame:summary(draws.slice(1)),
    framesOver20ms:intervals.slice(1).filter(v=>v>20).length,framesOver50ms:intervals.slice(1).filter(v=>v>50).length,
    visibleTiles,tiles:tiles.length,minutes,diagnostics:{...waveformRenderer.diagnostics},
    wallSeconds:(Date.now()-wallStart)/1000,renderedRatio:elapsed/((Date.now()-wallStart)/1000),
    stalls,throttled,
    note:'rAF timestamps measure when the callback ran, not display photon time',
  });
}
requestAnimationFrame(frame);
