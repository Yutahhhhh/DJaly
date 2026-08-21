import { useEffect, useState } from "react";
import * as api from "../api/client";
import type { BackupInfo, BackupUsage } from "../types";

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  const units = ["KB", "MB", "GB", "TB"];
  let value = bytes / 1024;
  let unitIndex = 0;
  while (value >= 1024 && unitIndex < units.length - 1) {
    value /= 1024;
    unitIndex++;
  }
  return `${value.toFixed(1)} ${units[unitIndex]}`;
}

/** Lists backups and storage usage statistics. */
export function BackupPanel() {
  const [backups, setBackups] = useState<BackupInfo[]>([]);
  const [usage, setUsage] = useState<BackupUsage | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([api.getBackups(), api.getBackupUsage()])
      .then(([b, u]) => {
        setBackups(b);
        setUsage(u);
      })
      .catch((e) => setError(e instanceof Error ? e.message : String(e)));
  }, []);

  return (
    <div className="backup-panel">
      <h3>Backups</h3>
      {error && <div className="error-banner">{error}</div>}
      {usage && (
        <dl className="backup-panel__usage">
          <div>
            <dt>Total</dt>
            <dd>{usage.total_backups}</dd>
          </div>
          <div>
            <dt>Size</dt>
            <dd>{formatBytes(usage.total_size_bytes)}</dd>
          </div>
          <div>
            <dt>Compressed</dt>
            <dd>{formatBytes(usage.total_compressed_bytes)}</dd>
          </div>
          <div>
            <dt>Protected</dt>
            <dd>{usage.protected_count}</dd>
          </div>
        </dl>
      )}
      <ul className="backup-panel__list">
        {backups.map((b) => (
          <li key={b.id} className="backup-panel__item">
            <span className="backup-panel__name">{b.name}</span>
            <span className="backup-panel__type">{b.type}</span>
            <span className="backup-panel__size">{formatBytes(b.size_bytes)}</span>
            {b.is_protected && <span className="backup-panel__protected">🔒</span>}
          </li>
        ))}
        {backups.length === 0 && <li className="backup-panel__empty">No backups yet</li>}
      </ul>
    </div>
  );
}
