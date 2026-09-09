// Isolated interactive regression fixture; not imported by the application.
import React, { useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import { BeatGridEditor } from "../src/components/play/BeatGridEditor";
import { DeckWaveform } from "../src/components/play/DeckWaveform";
import type { PerformanceBeatGrid } from "../src/types/performance-metadata";
import "../src/components/play/play-workspace.css";
import "../src/components/play/play-density.css";
const source: PerformanceBeatGrid = { bpm: 120, first_beat_ms: 100, beats_per_bar: 4, beat_times_ms: Array.from({length:60}, (_,i) => 100 + (i < 30 ? i*500 : 15000+(i-30)*450)), beat_numbers: Array.from({length:60},(_,i)=>i%4+1), source:"rekordbox" };
function Fixture() {
  const scratches = useRef<unknown[]>([]);
  const [grid,setGrid] = useState(source), [playing,setPlaying]=useState(false), [position,setPosition]=useState(5100), [seekCount,setSeekCount]=useState(0), [saved,setSaved]=useState<PerformanceBeatGrid|null>(null);
  const [shift,setShift]=useState<{sequence:number;deltaMs:number}|null>(null), [vertical,setVertical]=useState(false), [compact,setCompact]=useState(false);
  useEffect(()=>{if(!playing)return;const timer=setInterval(()=>setPosition(p=>p+20),20);return()=>clearInterval(timer)},[playing]);
  return <main className={`dj-workspace ${compact?"dj-workspace--compact":""}`} style={{height:"100vh",minWidth:940}}>
    <header className="dj-global-bar"><strong>GRID INTERACTION TEST</strong><button className="dj-button" onClick={()=>setVertical(!vertical)}>縦横切替</button><button className="dj-button" onClick={()=>setCompact(!compact)}>密度切替</button></header>
    <div style={{height:vertical?360:180,position:"relative"}}><DeckWaveform trackId={1} positionMs={position} durationMs={30000} bpm={grid.bpm} beatgridOffsetMs={grid.first_beat_ms} beatTimesMs={grid.beat_times_ms??undefined} beatNumbers={grid.beat_numbers??undefined} layout={vertical?"vertical":"horizontal"} side="left" color="cyan" label="A" mode="scroll" playing={playing} onSeek={ms=>{setPosition(ms);setSeekCount(n=>n+1)}} onScratch={async command=>{scratches.current.push(command); document.querySelector('#scratch-result')!.textContent=JSON.stringify(scratches.current)}} onGridShift={deltaMs=>setShift(old=>({sequence:(old?.sequence??0)+1,deltaMs}))}/></div>
    <section className="dj-deck-pair"><div className="dj-deck"><div className="dj-track-info">Variable tempo test · GRID EDIT</div><div className="dj-deck-controls"><div className="dj-perf"><BeatGridEditor trackId={1} durationMs={30000} positionMs={position} initialGrid={source} hasGrid playing={playing} shiftRequest={shift} onTogglePlay={()=>setPlaying(!playing)} onPreview={value=>setGrid(value??source)} onClose={()=>{}} onSave={async value=>{setSaved(value)}} onRekordbox={async()=>source} onAnalyze={async()=>({...source,source:"analysis",confidence:2.4})}/></div></div></div><div className="dj-deck"><div className="dj-track-info">Deck B · untouched</div></div></section>
    <output id="result" style={{display:"none"}}>{JSON.stringify({first:grid.first_beat_ms,bpm:grid.bpm,beats:grid.beat_times_ms,seekCount,saved,position})}</output>
    <output id="scratch-result" style={{display:"none"}}>[]</output>
  </main>
}
createRoot(document.getElementById("root")!).render(<React.StrictMode><Fixture/></React.StrictMode>);
