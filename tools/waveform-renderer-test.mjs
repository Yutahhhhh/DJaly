import assert from 'node:assert/strict';
const {webkit}=await import(process.env.DJALY_PLAYWRIGHT_MODULE||'playwright');
const browser=await webkit.launch({headless:true});
try{
 const page=await browser.newPage({viewport:{width:1200,height:800},deviceScaleFactor:2});
 await page.goto(process.env.DJALY_TEST_UI||'http://127.0.0.1:1420');
 const result=await page.evaluate(async()=>{
  const {waveformRenderer:r}=await import('/src/services/waveform/renderer.ts');
  document.body.innerHTML='';document.body.style.background='#080b10';
  const bins=2048,fields=Array.from({length:6},()=>new Float32Array(bins*2)),counts=new Uint32Array(bins).fill(64);
  for(let c=0;c<2;c++)for(let b=0;b<bins;b++){const i=c*bins+b,peak=b===1024?.95:.15+.3*Math.abs(Math.sin(b*.04));fields[0][i]=-peak;fields[1][i]=peak;fields[2][i]=peak*peak*.4;fields[3][i]=fields[2][i]*(1-b/bins);fields[4][i]=fields[2][i]*.2;fields[5][i]=fields[2][i]*b/bins;}
  const tile={lod:0,channels:2,bins,framesPerBin:64,startFrame:0,coveredFrames:bins*64,sampleRate:48000,bands:true,counts,fields};
  const surfaces=Array.from({length:4},()=>{const canvas=document.createElement('canvas');canvas.width=2400;canvas.height=192;canvas.style.width='1200px';canvas.style.height='96px';document.body.append(canvas);const ctx=canvas.getContext('2d');ctx.scale(2,2);return ctx;});
  const draw=at=>{for(const ctx of surfaces){ctx.clearRect(0,0,1200,96);r.draw(ctx,[tile],at,2730.6666667,1200,96,false,'left');}};
  draw(0);const warmUploads=r.diagnostics.uploads,warmRasterUploads=r.diagnostics.rasterUploads;
  const times=[];for(let i=0;i<120;i++){const start=performance.now();draw(i*.1);times.push(performance.now()-start);}
  const stableUploads=r.diagnostics.uploads===warmUploads&&r.diagnostics.rasterUploads===warmRasterUploads;
  draw(0);const gpu=surfaces[0].getImageData(0,0,2400,192).data;const gpuPixels=gpu.filter((_,i)=>i%4===3&&gpu[i]>0).length;
  r.forceCanvas=true;draw(0);const cpu=surfaces[0].getImageData(0,0,2400,192).data;const cpuPixels=cpu.filter((_,i)=>i%4===3&&cpu[i]>0).length;r.forceCanvas=false;
  const extension=r.canvas.getContext('webgl2').getExtension('WEBGL_lose_context');
  if(!extension)throw Error('Context-loss testing requires WEBGL_lose_context');
  const waitEvent=name=>new Promise((resolve,reject)=>{const timer=setTimeout(()=>reject(Error(name+' timed out')),3000);r.canvas.addEventListener(name,()=>{clearTimeout(timer);resolve();},{once:true});});
  let event=waitEvent('webglcontextlost');extension.loseContext();await event;draw(0);
  const fallback=r.diagnostics.backend==='canvas2d';
  // WebKit finishes the lost-event dispatch before it permits restoration.
  await new Promise(resolve=>setTimeout(resolve,100));
  event=waitEvent('webglcontextrestored');extension.restoreContext();await event;draw(0);
  const restored=r.diagnostics.backend==='webgl2';
  // Cycle well beyond both caches: retained rasters and VBOs must stay bounded.
  for(let i=0;i<80;i++)r.draw(surfaces[0],[{...tile,startFrame:i*131072}],i*131072/48,2730.6666667,1200,96,false,'left');
  const bounded=r.diagnostics.gpuBytes<=32*1024*1024&&r.diagnostics.rasterBytes<=32*1024*1024;
  draw(0);
  times.sort((a,b)=>a-b);return {stableUploads,gpuPixels,cpuPixels,fallback,restored,bounded,p95:times[114],p99:times[118],diagnostics:r.diagnostics};
 });
 assert(result.fallback&&result.restored,'context loss must fall back and recover');assert(result.bounded);
 assert(result.stableUploads,'steady scrolling must reuse geometry');assert(result.gpuPixels>10000&&result.cpuPixels>10000,'both renderers must produce visible waveforms');assert(result.diagnostics.gpuBytes<=32*1024*1024);assert(result.diagnostics.rasterBytes<=32*1024*1024);
 await page.screenshot({path:'/tmp/djaly-deck-waveform-renderer.png'});console.log(JSON.stringify(result));
}finally{await browser.close();}
