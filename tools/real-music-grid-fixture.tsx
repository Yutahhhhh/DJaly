// Production editor and waveform against isolated, real API/native processes.
import React, {useEffect, useState} from 'react';
import {createRoot} from 'react-dom/client';
import {BeatGridEditor} from '../src/components/play/BeatGridEditor';
import {DeckWaveform} from '../src/components/play/DeckWaveform';
import type {PerformanceBeatGrid, PerformanceMetadata} from '../src/types/performance-metadata';
import '../src/components/play/play-workspace.css';
import '../src/components/play/play-density.css';

async function request(url:string, body?:unknown, method='POST') {
  const response=await fetch(url,body===undefined?undefined:{method,headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  if(!response.ok)throw Error(await response.text());
  return response.json();
}
const native=(op:string,params:unknown={})=>request('/validation/native',{op,params});
function Fixture(){
 const [item,setItem]=useState<{id:number;durationMs:number;path:string;metadata:PerformanceMetadata}|null>(null);
 const [grid,setGrid]=useState<PerformanceBeatGrid|null>(null),[position,setPosition]=useState(60000),[playing,setPlaying]=useState(false),[saved,setSaved]=useState(0);
 const [shift,setShift]=useState<{sequence:number;deltaMs:number}|null>(null),[error,setError]=useState('');
 const fail=(e:unknown)=>{setError(String(e));console.error(e);};
 useEffect(()=>{void(async()=>{
   const bundle=await request('/validation/bundle');
   const selected=bundle[Number(new URLSearchParams(location.search).get('track')||0)];
   selected.metadata=await request(`/api/tracks/${selected.id}/performance-metadata`);
   const g=selected.metadata.beat_grid;
   await native('deck.load',{deck:'A',track:{trackId:String(selected.id),path:selected.path,bpm:g.bpm,beatgridOffsetMs:g.first_beat_ms,beatTimesMs:g.beat_times_ms??undefined}});
   for(let i=0;i<200;i++){const s=await native('state.snapshot');if(s.decks.A.track?.trackId===String(selected.id))break;await new Promise(r=>setTimeout(r,25));}
   await native('deck.seek',{deck:'A',positionMs:60000});setItem(selected);setGrid(g);
 })().catch(fail);},[]);
 useEffect(()=>{if(!item)return;const timer=setInterval(()=>{void native('state.snapshot').then(s=>{setPosition(s.decks.A.positionMs);setPlaying(s.decks.A.status==='playing');}).catch(fail);},50);return()=>clearInterval(timer);},[item?.id]);
 if(!item||!grid)return <pre>{error||'Loading real song…'}</pre>;
 return <main className="dj-workspace" style={{height:'100vh',minWidth:940}}>
   <output id="error">{error}</output><output id="result" style={{display:"none"}}>{JSON.stringify({saved,position,playing,grid})}</output>
   <div style={{height:220}}><DeckWaveform trackId={item.id} label="A" positionMs={position} durationMs={item.durationMs} bpm={grid.bpm} beatgridOffsetMs={grid.first_beat_ms} beatTimesMs={grid.beat_times_ms??undefined} beatNumbers={grid.beat_numbers??undefined} layout="horizontal" side="left" color="cyan" mode="scroll" playing={playing}
     onGridShift={deltaMs=>setShift(old=>({sequence:(old?.sequence??0)+1,deltaMs}))}
     onSeek={positionMs=>{void native('deck.seek',{deck:'A',positionMs}).catch(fail);}}
     onScratch={command=>native('deck.scratch',{deck:'A',...command})} onScratchError={fail}/></div>
   <BeatGridEditor trackId={item.id} durationMs={item.durationMs} positionMs={position} initialGrid={item.metadata.beat_grid!} hasGrid playing={playing} shiftRequest={shift}
     onPreview={g=>setGrid(g??item.metadata.beat_grid!)} onClose={()=>{}}
     onTogglePlay={()=>{void native(playing?'deck.pause':'deck.play',{deck:'A'}).catch(fail);}}
     onAnalyze={()=>request(`/api/tracks/${item.id}/grid-analysis`,{force:false})}
     onSave={async g=>{
       const updated=await request(`/api/tracks/${item.id}/performance-metadata`,{revision:item.metadata.revision,cue_points:item.metadata.cue_points,loops:item.metadata.loops,beat_grid:g},'PUT');
       await native('deck.beatgrid.set',{deck:'A',trackId:String(item.id),bpm:g.bpm,firstBeatMs:g.first_beat_ms,beatsPerBar:g.beats_per_bar,beatTimesMs:g.beat_times_ms??undefined,beatNumbers:g.beat_numbers??undefined});
       const reloaded=await request(`/api/tracks/${item.id}/performance-metadata`);
       if(JSON.stringify(reloaded)!==JSON.stringify(updated))throw Error('Saved grid did not round trip');
       setItem({...item,metadata:updated});setSaved(n=>n+1);
     }}/>
 </main>;
}
createRoot(document.getElementById('root')!).render(<Fixture/>);
