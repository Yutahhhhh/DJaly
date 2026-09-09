export interface WaveformTile {
  lod:number; channels:number; bins:number; framesPerBin:number; startFrame:number; coveredFrames:number;
  sampleRate:number; bands:boolean; counts:Uint32Array; fields:Float32Array[];
}
export function crc32(bytes:Uint8Array) {
  let crc=0xffffffff;
  for(const byte of bytes){crc^=byte;for(let bit=0;bit<8;bit++)crc=(crc>>>1)^(0xedb88320&-(crc&1));}
  return (crc^0xffffffff)>>>0;
}
export function parseTile(buffer:ArrayBuffer):WaveformTile {
  const fail=():never=>{throw new Error('Invalid waveform tile');};
  if(buffer.byteLength<64)return fail();
  const v=new DataView(buffer),u16=(at:number)=>v.getUint16(at,true),u32=(at:number)=>v.getUint32(at,true);
  if(v.getUint32(0,false)!==0x444a5756||u16(4)!==2||u16(6)!==64||u32(8)>1||u32(52)!==6||v.getBigUint64(56,true)!==0n)return fail();
  const channels=u16(12),lod=u16(14),bins=u32(16),framesPerBin=u32(20),payload=u32(44);
  const start=v.getBigInt64(24,true),covered=v.getBigUint64(32,true);
  if(![1,2].includes(channels)||lod>25||bins<1||bins>2048||framesPerBin!==64*2**lod||u32(40)===0
    ||start<BigInt(-Number.MAX_SAFE_INTEGER)||start>BigInt(Number.MAX_SAFE_INTEGER)||covered>BigInt(Number.MAX_SAFE_INTEGER)
    ||payload!==4*bins+24*channels*bins||buffer.byteLength!==64+payload||crc32(new Uint8Array(buffer,64))!==u32(48))return fail();
  const counts=new Uint32Array(bins),fields=Array.from({length:6},()=>new Float32Array(channels*bins));
  let total=0;
  for(let b=0;b<bins;b++){counts[b]=u32(64+b*4);if(!counts[b]||counts[b]>framesPerBin||b<bins-1&&counts[b]!==framesPerBin)return fail();total+=counts[b];}
  if(total!==Number(covered)||!Number.isSafeInteger(Number(start)+total))return fail();
  for(let f=0;f<6;f++)for(let i=0;i<channels*bins;i++){
    const x=v.getFloat32(64+4*bins+4*(f*channels*bins+i),true);
    if(!Number.isFinite(x)||f>=2&&x<0||f>=3&&!(u32(8)&1)&&x!==0)return fail();fields[f][i]=x;
  }
  for(let i=0;i<channels*bins;i++)if(fields[0][i]>fields[1][i])return fail();
  return {lod,channels,bins,framesPerBin,startFrame:Number(start),coveredFrames:total,sampleRate:u32(40),bands:!!(u32(8)&1),counts,fields};
}
export function chooseLod(framesPerPixel:number){return Math.max(0,Math.min(25,Math.floor(Math.log2(Math.max(64,framesPerPixel)/64))));}

/** DJWP is channel-major PCM, without the DJWV validCount array. */
export function parsePcmWindow(buffer:ArrayBuffer,framesPerBin:number):WaveformTile {
  const fail=():never=>{throw new Error('Invalid waveform PCM window');};
  if(buffer.byteLength<64||!Number.isSafeInteger(framesPerBin)||framesPerBin<1)return fail();
  const v=new DataView(buffer),count=v.getUint32(16,true),channels=v.getUint16(12,true),rate=v.getUint32(40,true);
  const start=Number(v.getBigInt64(24,true));
  if(v.getUint32(0,false)!==0x444a5750||v.getUint16(4,true)!==2||v.getUint16(6,true)!==64||v.getUint32(8,true)!==0||v.getUint16(14,true)!==0||v.getUint32(20,true)!==1||v.getUint32(52,true)!==1||v.getBigUint64(56,true)!==0n
    ||!count||count>262144||![1,2].includes(channels)||!rate||!Number.isSafeInteger(start)||!Number.isSafeInteger(start+count)||v.getBigUint64(32,true)!==BigInt(count)||v.getUint32(44,true)!==count*channels*4||buffer.byteLength!==64+count*channels*4||crc32(new Uint8Array(buffer,64))!==v.getUint32(48,true))return fail();
  const bins=Math.ceil(count/framesPerBin);if(bins>8192)return fail();
  const counts=new Uint32Array(bins),fields=Array.from({length:6},()=>new Float32Array(channels*bins));
  for(let b=0;b<bins;b++){
    const from=b*framesPerBin,to=Math.min(count,from+framesPerBin);counts[b]=to-from;
    for(let c=0;c<channels;c++){
      let min=Infinity,max=-Infinity,energy=0;
      for(let f=from;f<to;f++){const x=v.getFloat32(64+4*(c*count+f),true);if(!Number.isFinite(x))return fail();min=Math.min(min,x);max=Math.max(max,x);energy+=x*x;}
      const i=c*bins+b;fields[0][i]=min;fields[1][i]=max;fields[2][i]=energy/(to-from);
    }
  }
  return {lod:0,channels,bins,framesPerBin,startFrame:start,coveredFrames:count,sampleRate:rate,bands:false,counts,fields};
}
