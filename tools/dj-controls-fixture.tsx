import React, { useState } from "react";
import "../src/index.css";
import { createRoot } from "react-dom/client";
import { SoftwareDeck } from "../src/components/play/SoftwareDeck";
import type { DeckState, ChannelState } from "../src/types/dj-engine";
import "../src/components/play/play-workspace.css";
import "../src/components/play/play-density.css";
const noop = () => {};
const capabilities = ["deck.hotcue", "deck.loop", "deck.beatjump", "deck.quantize", "deck.tempo", "deck.beatgrid", "deck.keylock", "deck.sync", "deck.transport", "mixer.eq", "mixer.filter", "mixer.trim", "mixer.fx", "mixer.channel.gain"];
function Fixture() {
  const [compact, setCompact] = useState(false), [four,setFour] = useState(false);
  const [events,setEvents] = useState<unknown[]>([]);
  const [channel,setChannel] = useState<ChannelState>({gain:1,eqLow:1,eqMid:1,eqHigh:1,trim:1,filter:0});
  const [deck,setDeck] = useState<DeckState>({deck:"A",status:"playing",track:{trackId:"1",path:"/fixture.wav",title:"Controls verification",artist:"Test fixture",durationMs:30000,bpm:120,sampleRateHz:44100,channels:2,beatgridOffsetMs:0},positionMs:4000,positionFrames:176400,rate:1,keylock:false,syncEnabled:false,syncLeader:null,effectiveBpm:120,hotCues:Array(8).fill(null),loopRegion:null,lastError:null,loadId:null});
  const record = (value:unknown) => setEvents(old=>[...old,value]);
  return <main className={`dj-workspace ${compact?"dj-workspace--compact":""} ${four?"dj-workspace--four":""}`} style={{height:"100vh"}}>
    <header className="dj-global-bar"><button onClick={()=>setCompact(!compact)}>Density</button><button onClick={()=>setFour(!four)}>Deck count</button></header>
    <div className="dj-deck-pair">{(["A","B"] as const).map(id=><SoftwareDeck key={id} id={id} deck={{...deck,deck:id}} channel={channel} active connected capability capabilities={capabilities} gain={1}
      onActivate={noop} onToggle={noop} onCue={noop} onSeek={noop} onSeekAbsolute={noop} onGain={noop} onTempo={noop} onKeylock={noop} onSync={noop} onUnload={noop} onGridEdit={noop}
      onHotCue={(slot,clear)=>{record({cue:slot,clear});setDeck(old=>({...old,hotCues:old.hotCues.map((v,i)=>i===slot?clear?null:4000:v)}))}}
      onLoop={beats=>record({loop:beats})} onBeatLoop={beats=>record({loop:beats})} onBeatJump={beats=>record({jump:beats})} onLoopEnable={enabled=>record({loopEnabled:enabled})} onQuantize={enabled=>record({quantize:enabled})}
      onTrim={value=>{record({trim:value});setChannel(old=>({...old,trim:value}))}} onFilter={value=>{record({filter:value});setChannel(old=>({...old,filter:value}))}} onEq={(band,value)=>record({band,value})}
      onFx={(effect,enabled,mix)=>{record({effect,enabled,mix});setChannel(old=>({...old,fx:{effect,enabled,mix}}))}} />)}</div>
    <output id="events" hidden>{JSON.stringify(events)}</output>
  </main>;
}
createRoot(document.getElementById("root")!).render(<Fixture/>);
