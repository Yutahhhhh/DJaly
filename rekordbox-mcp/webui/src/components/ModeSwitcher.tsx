import { useState } from "react";
import * as api from "../api/client";
import type { OperationMode } from "../types";

interface ModeSwitcherProps {
  mode: OperationMode | null;
  onModeChanged: (mode: OperationMode) => void;
}

const MODE_DESCRIPTIONS: Record<OperationMode, string> = {
  readonly: "Read-only access to tracks, cues, playlists",
  xml: "Export cues to Rekordbox collection XML (Automark compatible)",
  masterdb: "Direct database writes (requires Rekordbox to be closed)",
};

/** Switches between readonly / xml / masterdb operation modes. */
export function ModeSwitcher({ mode, onModeChanged }: ModeSwitcherProps) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleChange(newMode: OperationMode) {
    setBusy(true);
    setError(null);
    try {
      const result = await api.setMode(newMode);
      onModeChanged(result.mode);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mode-switcher">
      <h3>Operation mode</h3>
      {error && <div className="error-banner">{error}</div>}
      <div className="mode-switcher__options">
        {(["readonly", "xml", "masterdb"] as OperationMode[]).map((m) => (
          <button
            key={m}
            disabled={busy}
            className={`mode-switcher__option${mode === m ? " mode-switcher__option--active" : ""}`}
            onClick={() => handleChange(m)}
            title={MODE_DESCRIPTIONS[m]}
          >
            {m}
          </button>
        ))}
      </div>
      {mode && <p className="mode-switcher__desc">{MODE_DESCRIPTIONS[mode]}</p>}
    </div>
  );
}
