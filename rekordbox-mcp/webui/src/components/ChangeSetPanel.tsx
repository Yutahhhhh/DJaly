import { FormEvent, useCallback, useEffect, useState } from "react";
import * as api from "../api/client";
import type { AuditLogEntry, ChangeSet, ChangeSetItem } from "../types";

function message(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function formatValue(value: Record<string, unknown> | null): string {
  return value == null ? "—" : JSON.stringify(value);
}

/** Review, approve, and audit atomic changes before they reach Rekordbox. */
export function ChangeSetPanel() {
  const [changesets, setChangesets] = useState<ChangeSet[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [preview, setPreview] = useState<(ChangeSet & { changes: ChangeSetItem[] }) | null>(null);
  const [logs, setLogs] = useState<AuditLogEntry[]>([]);
  const [name, setName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    Promise.all([api.listChangesets(), api.getAuditLog()])
      .then(([items, audit]) => {
        setChangesets(items);
        setLogs(audit);
        if (!selectedId && items[0]) setSelectedId(items[0].id);
      })
      .catch((e) => setError(message(e)));
  }, [selectedId]);

  useEffect(() => { load(); }, [load]);

  useEffect(() => {
    if (!selectedId) { setPreview(null); return; }
    api.previewChangeset(selectedId).then(setPreview).catch((e) => setError(message(e)));
  }, [selectedId]);

  function create(event: FormEvent) {
    event.preventDefault();
    if (!name.trim()) return;
    setBusy(true); setError(null);
    api.createChangeset(name.trim()).then((created) => {
      setName(""); setSelectedId(created.id); load();
    }).catch((e) => setError(message(e))).finally(() => setBusy(false));
  }

  function run(action: "apply" | "undo" | "rollback", dryRun = false) {
    if (!selectedId) return;
    setBusy(true); setError(null);
    const operation = action === "apply" ? api.applyChangeset(selectedId, dryRun)
      : action === "undo" ? api.undoChangeset(selectedId) : api.rollbackChangeset(selectedId);
    operation.then((result) => {
      if (!result.success) throw new Error(result.error ?? `${action} failed`);
      load();
      return api.previewChangeset(selectedId).then(setPreview);
    }).catch((e) => setError(message(e))).finally(() => setBusy(false));
  }

  const selected = changesets.find((item) => item.id === selectedId);
  return (
    <section className="changeset-panel">
      <div className="changeset-panel__header"><h2>ChangeSets</h2><span className="changeset-panel__hint">Review before applying</span></div>
      {error && <div className="error-banner">{error}</div>}
      <form className="changeset-panel__create" onSubmit={create}>
        <input value={name} onChange={(e) => setName(e.target.value)} placeholder="ChangeSet name" aria-label="ChangeSet name" />
        <button type="submit" disabled={busy || !name.trim()}>Create</button>
      </form>
      <div className="changeset-panel__columns">
        <div>
          <h3>Pending and completed</h3>
          <ul className="changeset-panel__list">
            {changesets.map((item) => (
              <li key={item.id} className={`changeset-panel__item${item.id === selectedId ? " changeset-panel__item--selected" : ""}`} onClick={() => setSelectedId(item.id)}>
                <strong>{item.name}</strong><span>{item.item_count} changes · {item.is_applied ? "Applied" : item.is_rolled_back ? "Rolled back" : "Pending"}</span>
              </li>
            ))}
            {!changesets.length && <li className="changeset-panel__empty">No ChangeSets yet</li>}
          </ul>
        </div>
        <div className="changeset-panel__detail">
          {selected && preview ? <>
            <h3>{preview.name}</h3>
            <div className="changeset-panel__actions">
              <button onClick={() => run("apply", true)} disabled={busy || selected.is_applied || selected.is_rolled_back}>Validate</button>
              <button className="changeset-panel__apply" onClick={() => run("apply")} disabled={busy || selected.is_applied || selected.is_rolled_back}>Apply</button>
              <button onClick={() => run("undo")} disabled={busy || !selected.is_applied}>Undo</button>
              <button className="changeset-panel__rollback" onClick={() => run("rollback")} disabled={busy || !selected.is_applied}>Rollback</button>
            </div>
            <ul className="changeset-panel__preview">
              {preview.changes.map((change) => <li key={change.id}><span className="changeset-panel__change-label">{change.action} {change.entity_type}:{change.entity_id}</span><code>{formatValue(change.old_data)} → {formatValue(change.new_data)}</code></li>)}
              {!preview.changes.length && <li className="changeset-panel__empty">No changes in this ChangeSet</li>}
            </ul>
          </> : <p className="changeset-panel__empty">Select a ChangeSet to preview.</p>}
        </div>
      </div>
      <details className="changeset-panel__audit"><summary>Audit log ({logs.length})</summary><ul>
        {logs.map((log) => <li key={log.id}><span>{new Date(log.timestamp).toLocaleString()}</span> {log.operation} <code>{log.entity_type}:{log.entity_id}</code>{log.success ? "" : ` — ${log.error ?? "failed"}`}</li>)}
        {!logs.length && <li className="changeset-panel__empty">No audit entries</li>}
      </ul></details>
    </section>
  );
}
