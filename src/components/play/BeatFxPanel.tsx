import { useState } from "react";
import { djEngineClient } from "@/services/dj-engine/client";
import type { MixerState } from "@/types/dj-engine";
import { BEAT_FX, beatFxMaxBeats } from "@/services/midi/beat-fx";
export function BeatFxPanel({state, enabled}: {state?: MixerState['beatFx']; enabled: boolean}) {
  const [error,setError]=useState("");
  const set=(params:Record<string,unknown>)=>{setError("");void djEngineClient.send("mixer.beatfx.set",params).catch(e=>setError(String(e)));};
  return <section className="dj-sampler-toolbar" aria-label="BEAT FX" style={{padding:8}}><strong>BEAT FX</strong>
    <select aria-label="BEAT FX種類" disabled={!enabled} value={state?.effect??"echo"} onChange={e=>set({effect:e.target.value})}>{BEAT_FX.map(([effect,label])=><option key={effect} value={effect}>{label}</option>)}</select>
    <select aria-label="BEAT FX対象" disabled={!enabled} value={state?.target??"A"} onChange={e=>set({target:e.target.value})}>{["A","B","C","D","master","mic","sampler"].map(target=><option key={target} value={target}>{target.toUpperCase()}</option>)}</select>
    <button disabled={!enabled} aria-pressed={state?.auto!==false} onClick={()=>set({auto:true})}>AUTO BPM</button>
    <label>BPM <input aria-label="BEAT FX BPM" type="number" min="40" max="300" step=".1" disabled={!enabled} value={state?.bpm || ""} placeholder="AUTO" onChange={e=>{const bpm=Number(e.target.value); if(bpm>=40 && bpm<=300) set({bpm});}} /></label>
    <label>拍数 <select disabled={!enabled} value={state?.beats??1} onChange={e=>set({beats:Number(e.target.value)})}>{[.125,.25,.5,1,2,4,8,16].filter(beats=>beats<=beatFxMaxBeats(state?.effect??"echo")).map(beats=><option key={beats} value={beats}>{beats}</option>)}</select></label>
    <label>LEVEL/DEPTH <input aria-label="BEAT FX LEVEL/DEPTH" disabled={!enabled} type="range" min="0" max="1" step=".01" value={state?.mix??.5} onChange={e=>set({mix:Number(e.target.value)})}/></label>
    <button disabled={!enabled} aria-pressed={state?.enabled??false} onClick={()=>set({enabled:!state?.enabled})}>{state?.enabled?"ON":"OFF"}</button>{error&&<small role="alert">{error}</small>}
  </section>;
}
