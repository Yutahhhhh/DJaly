import { useEffect, useState } from "react";
import { djEngineClient } from "@/services/dj-engine/client";
import { memoryAction, memoryCues } from "@/services/dj-engine/memory-cues";
import type { DeckId, DeckState } from "@/types/dj-engine";
export function DeckPerformanceControls({ deck, id, enabled }: { deck?: DeckState; id: DeckId; enabled: boolean }) {
  const [error, setError] = useState("");
  const [, redraw] = useState(0);
  useEffect(()=>{const changed=()=>redraw(v=>v+1);window.addEventListener("djaly:memory-cues",changed);return()=>window.removeEventListener("djaly:memory-cues",changed);},[]);
  const run = (task: () => Promise<unknown>) => { setError(""); void task().then(() => redraw(v=>v+1)).catch(e=>setError(String(e))); };
  const command = (op: string, params: Record<string, unknown> = {}) => run(()=>djEngineClient.send(op,{deck:id,trackId:deck?.track?.trackId,...params}));
  const points = deck?.track ? memoryCues(deck.track.trackId,deck.track.durationMs) : [];
  return <div className="dj-deck-performance-controls">
    <div><button disabled={!enabled} aria-pressed={Boolean(deck?.slip)} onClick={()=>command("deck.slip.set",{enabled:!deck?.slip})}>SLIP</button>
      <button disabled={!enabled} aria-pressed={Boolean(deck?.reverse)} onClick={()=>command("deck.reverse.set",{enabled:!deck?.reverse})}>REVERSE</button>
      <button disabled={!enabled} onClick={()=>command("deck.key.shift",{semitones:Math.max(-12,(deck?.keyShift??0)-1)})}>KEY −</button><span>{(deck?.keyShift??0).toFixed(0)}</span>
      <button disabled={!enabled} onClick={()=>command("deck.key.shift",{semitones:Math.min(12,(deck?.keyShift??0)+1)})}>KEY ＋</button>
      <button disabled={!enabled} onClick={()=>command("deck.key.reset")}>RESET</button><button disabled={!enabled} onClick={()=>command("deck.key.sync")}>KEY SYNC</button></div>
    <div><span>MEMORY {points.length}</span>{([['previous','◀'],['save','保存'],['delete','削除'],['next','▶']] as const).map(([action,label])=><button key={action} disabled={!enabled} onClick={()=>run(()=>memoryAction(id,action))}>{label}</button>)}</div>
    {error&&<small role="alert">{error}</small>}
  </div>;
}
