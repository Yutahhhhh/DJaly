import React from "react";
import { createRoot } from "react-dom/client";
import "../src/index.css";
import { PlayWorkspace } from "../src/components/play/PlayWorkspace";
createRoot(document.getElementById("root")!).render(<div style={{ height: "100vh" }}><PlayWorkspace /></div>);
