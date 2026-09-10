import type { WaveformTile } from './protocol';
import { drawWaveformTiles } from './draw';
type Raster={tile:number;key:string;canvas:HTMLCanvasElement;bytes:number;used:number};
type Geometry={buffer:WebGLBuffer;count:number;bytes:number;used:number};
/** One WebGL context for all deck surfaces, with a bounded VBO cache. */
class WaveformRenderer {
  forceCanvas = false;
  private canvas:HTMLCanvasElement|null=null;
  private gl:WebGL2RenderingContext|null=null;
  private program:WebGLProgram|null=null;
  private failed=false;
  private position=0;
  private color=0;
  private viewport:WebGLUniformLocation|null=null;
  private orientation:WebGLUniformLocation|null=null;
  private geometry=new Map<number,Geometry>();
  // GPU/raster caches own rendered data, not the repository's parsed arrays.
  // Weak identities let CPU tiles be collected when their leases are released.
  private identities=new WeakMap<WaveformTile,number>();
  private nextIdentity=0;
  private identity(tile:WaveformTile){
    let id=this.identities.get(tile);
    if(id===undefined){id=++this.nextIdentity;this.identities.set(tile,id);}
    return id;
  }
  private bytes=0;
  private rasters:Raster[]=[];
  private rasterBytes=0;
  readonly diagnostics={backend:'canvas2d',fallbacks:0,draws:0,uploads:0,gpuBytes:0,rasterBytes:0,rasterUploads:0,cpuMs:0};
  private initialize(){
    if(this.canvas||this.failed)return;
    const canvas=document.createElement('canvas');
    const gl=canvas.getContext('webgl2',{antialias:false,alpha:true,premultipliedAlpha:false,preserveDrawingBuffer:true});
    if(!gl){this.failed=true;return;}
    try{
      const shader=(type:number,source:string)=>{const s=gl.createShader(type);if(!s)throw new Error('shader');gl.shaderSource(s,source);gl.compileShader(s);if(!gl.getShaderParameter(s,gl.COMPILE_STATUS)){gl.deleteShader(s);throw new Error('compile');}return s;};
      const vertex=shader(gl.VERTEX_SHADER,`#version 300 es
        in vec2 position;in vec3 color;out vec3 shade;
        uniform vec4 viewport;uniform vec2 orientation;
        void main(){float time=viewport.x+position.x*viewport.y;float amplitude=position.y*viewport.z;
          vec2 p=orientation.x>0.5?vec2(viewport.w+orientation.y*amplitude,time):vec2(time,0.5+(gl_InstanceID==0?-amplitude:amplitude));
          gl_Position=vec4(p.x*2.0-1.0,1.0-p.y*2.0,0,1);shade=color;}`);
      const fragment=shader(gl.FRAGMENT_SHADER,`#version 300 es
        precision mediump float;in vec3 shade;out vec4 outputColor;void main(){outputColor=vec4(shade,1);}`);
      const program=gl.createProgram();if(!program)throw new Error('program');
      gl.attachShader(program,vertex);gl.attachShader(program,fragment);gl.linkProgram(program);gl.deleteShader(vertex);gl.deleteShader(fragment);
      if(!gl.getProgramParameter(program,gl.LINK_STATUS)){gl.deleteProgram(program);throw new Error('link');}
      this.canvas=canvas;this.gl=gl;this.program=program;
      this.position=gl.getAttribLocation(program,'position');this.color=gl.getAttribLocation(program,'color');
      this.viewport=gl.getUniformLocation(program,'viewport');this.orientation=gl.getUniformLocation(program,'orientation');
      canvas.addEventListener('webglcontextlost',event=>{event.preventDefault();this.geometry.clear();this.bytes=0;this.diagnostics.gpuBytes=0;this.gl=null;this.diagnostics.fallbacks++;});
      canvas.addEventListener('webglcontextrestored',()=>{this.canvas=null;this.program=null;this.failed=false;this.initialize();});
      this.diagnostics.backend='webgl2';
    }catch{this.failed=true;this.diagnostics.fallbacks++;}
  }
  private upload(tile:WaveformTile){
    const id=this.identity(tile);const old=this.geometry.get(id);if(old){old.used=performance.now();return old;}
    const vertices:number[]=[];
    const rectangle=(x:number,to:number,height:number,color:number[])=>{
      for(const [u,v] of [[x,0],[to,0],[x,height],[x,height],[to,0],[to,height]])vertices.push(u,v,...color);
    };
    for(let b=0;b<tile.bins;b++){
      let peak=0,energy=0,low=0,mid=0,high=0;
      for(let c=0;c<tile.channels;c++){const i=c*tile.bins+b;peak=Math.max(peak,Math.abs(tile.fields[0][i]),Math.abs(tile.fields[1][i]));energy+=tile.fields[2][i];low+=tile.fields[3][i];mid+=tile.fields[4][i];high+=tile.fields[5][i];}
      const x=b/2048,to=(b+tile.counts[b]/tile.framesPerBin)/2048;
      rectangle(x,to,Math.min(1,peak),[.72,.78,.87]);const sum=low+mid+high;
      const color=tile.bands&&sum>0?[(26*low+255*mid+233*high)/sum/255,(123*low+160*mid+241*high)/sum/255,(240*low+44*mid+255*high)/sum/255]:[.91,.95,1];
      rectangle(x,to,Math.min(1,Math.sqrt(energy/tile.channels)),color);
    }
    const data=new Float32Array(vertices),gl=this.gl!;
    for(const [key,item] of [...this.geometry].sort((a,b)=>a[1].used-b[1].used)){
      if(this.bytes+data.byteLength<=32*1024*1024)break;gl.deleteBuffer(item.buffer);this.bytes-=item.bytes;this.geometry.delete(key);
    }
    const buffer=gl.createBuffer();if(!buffer)throw new Error('buffer');gl.bindBuffer(gl.ARRAY_BUFFER,buffer);gl.bufferData(gl.ARRAY_BUFFER,data,gl.STATIC_DRAW);
    if(gl.getError()!==gl.NO_ERROR)throw new Error('upload');
    const item={buffer,count:vertices.length/5,bytes:data.byteLength,used:performance.now()};this.geometry.set(id,item);this.bytes+=item.bytes;this.diagnostics.uploads++;this.diagnostics.gpuBytes=this.bytes;return item;
  }
  draw(ctx:CanvasRenderingContext2D,tiles:WaveformTile[],startMs:number,spanMs:number,width:number,height:number,vertical:boolean,side:'left'|'right'){
    const start=performance.now();this.initialize();const gl=this.gl,canvas=this.canvas,program=this.program;
    if(gl&&canvas&&program&&!this.forceCanvas&&!tiles.some(tile=>tile.framesPerBin===1)){
      try{
        const dpr=Math.min(3,window.devicePixelRatio||1);
        const {position,color,viewport,orientation}=this;
        for(const tile of tiles){
          const spanFrames=spanMs*tile.sampleRate/1000;
          const length=(vertical?height:width)*tile.framesPerBin*2048/spanFrames;
          const w=Math.max(1,Math.ceil((vertical?width:length)*dpr));
          const h=Math.max(1,Math.ceil((vertical?length:height)*dpr));
          const bytes=w*h*4;
          if(w>8192||h>8192||bytes>32*1024*1024)throw new Error('raster budget');
          const key=`${w}:${h}:${vertical}:${vertical?side:''}`;
          const tileId=this.identity(tile);
          let raster=this.rasters.find(item=>item.tile===tileId&&item.key===key);
          if(!raster){
            while(this.rasterBytes+bytes>32*1024*1024){
              this.rasters.sort((a,b)=>a.used-b.used);
              const removed=this.rasters.shift()!;this.rasterBytes-=removed.bytes;
              removed.canvas.width=removed.canvas.height=0;
            }
            if(canvas.width!==w)canvas.width=w;if(canvas.height!==h)canvas.height=h;
            gl.viewport(0,0,w,h);gl.clearColor(0,0,0,0);gl.clear(gl.COLOR_BUFFER_BIT);gl.useProgram(program);
            gl.enableVertexAttribArray(position);gl.enableVertexAttribArray(color);
            const item=this.upload(tile);
            gl.bindBuffer(gl.ARRAY_BUFFER,item.buffer);gl.vertexAttribPointer(position,2,gl.FLOAT,false,20,0);gl.vertexAttribPointer(color,3,gl.FLOAT,false,20,8);
            const breadth=vertical?width:height;
            gl.uniform4f(viewport,0,1,(breadth-12)/breadth*(vertical?1:.5),side==='left'?1-2/width:2/width);
            gl.uniform2f(orientation,vertical?1:0,side==='left'?-1:1);gl.drawArraysInstanced(gl.TRIANGLES,0,item.count,vertical?1:2);
            const bitmap=document.createElement('canvas');bitmap.width=w;bitmap.height=h;
            bitmap.getContext('2d')!.drawImage(canvas,0,0);
            raster={tile:tileId,key,canvas:bitmap,bytes,used:0};this.rasters.push(raster);this.rasterBytes+=bytes;
            this.diagnostics.rasterBytes=this.rasterBytes;this.diagnostics.rasterUploads++;
          }
          raster.used=performance.now();
          const offset=(tile.startFrame-startMs*tile.sampleRate/1000)/spanFrames*(vertical?height:width);
          if(vertical)ctx.drawImage(raster.canvas,0,offset,width,length);
          else ctx.drawImage(raster.canvas,offset,0,length,height);
        }
        this.diagnostics.backend='webgl2';this.diagnostics.draws++;this.diagnostics.cpuMs=performance.now()-start;return;
      }catch{this.failed=true;for(const item of this.geometry.values())gl.deleteBuffer(item.buffer);this.geometry.clear();gl.deleteProgram(program);this.gl=null;this.bytes=0;this.diagnostics.fallbacks++;}
    }
    this.diagnostics.backend='canvas2d';drawWaveformTiles(ctx,tiles,startMs,spanMs,width,height,vertical,side);
    this.diagnostics.draws++;this.diagnostics.cpuMs=performance.now()-start;
  }
}
export const waveformRenderer=new WaveformRenderer();
