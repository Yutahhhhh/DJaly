import React, { useState } from "react";
import "../src/index.css";
import { createRoot } from "react-dom/client";
import { PlayLibrary } from "../src/components/play/PlayLibrary";
import "../src/components/play/play-workspace.css";
import "../src/components/play/play-density.css";
function Fixture() {
  const [loaded,setLoaded] = useState<number|null>(null);
  return <main className="dj-workspace" style={{height:"100vh"}}><PlayLibrary activeDeck="A" seedTrackId={1} onLoad={(_,track)=>setLoaded(track.id)}/><output hidden id="loaded">{loaded}</output></main>;
}
createRoot(document.getElementById("root")!).render(<Fixture/>);
