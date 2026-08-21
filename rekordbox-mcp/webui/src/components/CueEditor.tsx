import { useState } from "react";
import * as api from "../api/client";
import type { CuePoint } from "../types";

interface CueEditorProps {
  trackId: number;
  cues: CuePoint[];
  selectedCueId: string | null;
  onSelectCue: (cue: CuePoint) => void;
  onCuesChanged: () => void;
  proposedCues: CuePoint[];
  onProposedCuesChanged: (cues: CuePoint[]) => void;
  writeAllowed: boolean;
}

function labelFor(cue: CuePoint): string {
  return cue.kind === 0 ? "Memory" : `Hot ${cue.kind}`;
}

/** Add / delete / snap / generate cue points for the selected track. */
export function CueEditor({
  trackId,
  cues,
  selectedCueId,
  onSelectCue,
  onCuesChanged,
  proposedCues,
  onProposedCuesChanged,
  writeAllowed,
}: CueEditorProps) {
  const [newPositionMs, setNewPositionMs] = useState("0");
  const [newKind, setNewKind] = useState("1");
  const [newName, setNewName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [generateMode, setGenerateMode] = useState<"replace" | "merge" | "preserve">("preserve");
  const [notes, setNotes] = useState<string[]>([]);
  const [confidence, setConfidence] = useState<Record<string, number>>({});

  async function withBusy(fn: () => Promise<void>) {
    setBusy(true);
    setError(null);
    try {
      await fn();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  function handleAddHotCue() {
    withBusy(async () => {
      const positionMs = parseFloat(newPositionMs);
      const kind = parseInt(newKind, 10);
      if (kind === 0) {
        await api.addMemoryCue({ track_id: trackId, position_ms: positionMs, name: newName });
      } else {
        await api.addHotCue({ track_id: trackId, position_ms: positionMs, kind, name: newName });
      }
      onCuesChanged();
    });
  }

  function handleDelete(cue: CuePoint) {
    withBusy(async () => {
      await api.deleteCue(cue.id, trackId);
      onCuesChanged();
    });
  }

  function handleSnap(cue: CuePoint, grid: "beat" | "bar") {
    withBusy(async () => {
      await api.snapCueToBeatgrid(trackId, cue.id, grid);
      onCuesChanged();
    });
  }

  function handleGenerate() {
    withBusy(async () => {
      const result = await api.generateCues(trackId, "default", generateMode);
      onProposedCuesChanged(result.cues);
      setNotes(result.notes);
      setConfidence(result.confidence);
      onCuesChanged();
    });
  }

  function handleClearProposed() {
    onProposedCuesChanged([]);
    setNotes([]);
    setConfidence({});
  }

  return (
    <div className="cue-editor">
      <h3>Cue Editor</h3>
      {!writeAllowed && (
        <div className="warning-banner">
          Read-only mode: writes are disabled. Switch to <code>xml</code> or <code>masterdb</code> mode to edit cues.
        </div>
      )}
      {error && <div className="error-banner">{error}</div>}

      <section className="cue-editor__section">
        <h4>Add cue</h4>
        <div className="cue-editor__form-row">
          <label>
            Position (ms)
            <input
              type="number"
              value={newPositionMs}
              onChange={(e) => setNewPositionMs(e.target.value)}
            />
          </label>
          <label>
            Slot
            <select value={newKind} onChange={(e) => setNewKind(e.target.value)}>
              <option value="0">Memory</option>
              {[1, 2, 3, 5, 6, 7, 8, 9].map((k) => (
                <option key={k} value={k}>
                  Hot {k}
                </option>
              ))}
            </select>
          </label>
          <label>
            Name
            <input type="text" value={newName} onChange={(e) => setNewName(e.target.value)} />
          </label>
          <button disabled={busy || !writeAllowed} onClick={handleAddHotCue}>
            Add
          </button>
        </div>
      </section>

      <section className="cue-editor__section">
        <h4>Generate from Phrase / Vocal / BeatGrid</h4>
        <div className="cue-editor__form-row">
          <label>
            Mode
            <select value={generateMode} onChange={(e) => setGenerateMode(e.target.value as any)}>
              <option value="preserve">preserve (keep existing)</option>
              <option value="merge">merge</option>
              <option value="replace">replace</option>
            </select>
          </label>
          <button disabled={busy || !writeAllowed} onClick={handleGenerate}>
            Generate
          </button>
          {proposedCues.length > 0 && (
            <button disabled={busy} onClick={handleClearProposed}>
              Clear preview
            </button>
          )}
        </div>
        {notes.length > 0 && (
          <ul className="cue-editor__notes">
            {notes.map((n, i) => (
              <li key={i}>{n}</li>
            ))}
          </ul>
        )}
        {Object.keys(confidence).length > 0 && (
          <div className="cue-editor__confidence">
            {Object.entries(confidence).map(([pad, conf]) => (
              <span key={pad} className="cue-editor__confidence-pill">
                {pad}: {(conf * 100).toFixed(0)}%
              </span>
            ))}
          </div>
        )}
      </section>

      <section className="cue-editor__section">
        <h4>Existing cues ({cues.length})</h4>
        <table className="cue-editor__table">
          <thead>
            <tr>
              <th>Slot</th>
              <th>Position</th>
              <th>Comment</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {cues
              .slice()
              .sort((a, b) => a.position_ms - b.position_ms)
              .map((cue) => (
                <tr
                  key={cue.id}
                  className={cue.id === selectedCueId ? "cue-editor__row--selected" : ""}
                  onClick={() => onSelectCue(cue)}
                >
                  <td>{labelFor(cue)}</td>
                  <td>{(cue.position_ms / 1000).toFixed(2)}s</td>
                  <td>{cue.comment}</td>
                  <td className="cue-editor__row-actions">
                    <button disabled={busy || !writeAllowed} onClick={(e) => { e.stopPropagation(); handleSnap(cue, "beat"); }}>
                      Snap beat
                    </button>
                    <button disabled={busy || !writeAllowed} onClick={(e) => { e.stopPropagation(); handleSnap(cue, "bar"); }}>
                      Snap bar
                    </button>
                    <button disabled={busy || !writeAllowed} onClick={(e) => { e.stopPropagation(); handleDelete(cue); }}>
                      Delete
                    </button>
                  </td>
                </tr>
              ))}
            {cues.length === 0 && (
              <tr>
                <td colSpan={4} className="cue-editor__empty">
                  No cues yet
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </section>
    </div>
  );
}

export type { CueEditorProps };
