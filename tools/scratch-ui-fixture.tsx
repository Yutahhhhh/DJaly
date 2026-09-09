// Isolated UI test: records transport commands, does not pretend to render audio.
import React, { useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import { DeckWaveform } from "../src/components/play/DeckWaveform";
import "../src/components/play/play-workspace.css";
function Fixture() {
  const [position, setPosition] = useState(10000), [mounted, setMounted] = useState(true);
  const [vertical, setVertical] = useState(false), [track, setTrack] = useState(1);
  const commands = useRef<unknown[]>([]), seeks = useRef(0), held = useRef(false);
  const publish = () => {
    const result = document.querySelector("#result");
    if (result) result.textContent = JSON.stringify({ commands: commands.current, seeks: seeks.current, held: held.current });
  };
  useEffect(() => { const timer = setInterval(() => {
    if (!held.current) setPosition(p => p + 20);
    publish();
  }, 20); return () => clearInterval(timer); }, []);
  return <main>
    <button onClick={() => setMounted(v => !v)}>Mount</button>
    <button onClick={() => setVertical(v => !v)}>Orientation</button>
    <button onClick={() => setTrack(v => v + 1)}>Track</button>
    <div style={{ height: vertical ? 600 : 220, position: "relative" }}>
      {mounted && <DeckWaveform trackId={track} positionMs={position} durationMs={180000} layout={vertical ? "vertical" : "horizontal"} side="left" color="cyan" label="A" mode="scroll" playing bpm={120} onSeek={() => { seeks.current++; }}
        onScratch={async command => { commands.current.push(command); held.current = command.phase !== "end"; publish(); }} />}
    </div>
    <output id="result" style={{ display: "none" }} />
  </main>;
}
createRoot(document.getElementById("root")!).render(<React.StrictMode><Fixture /></React.StrictMode>);
