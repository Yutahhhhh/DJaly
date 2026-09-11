import { useState } from "react";
import { open } from "@tauri-apps/plugin-dialog";
import { Button } from "@/components/ui/button";

export function FolderSetting({ id, value, placeholder, onSelect }: { id: string; value: string; placeholder: string; onSelect: (path: string) => Promise<void> }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const choose = async () => {
    setBusy(true); setError("");
    try {
      const path = await open({ directory: true, multiple: false, defaultPath: value || undefined, title: "フォルダーを選択" });
      if (typeof path === "string") await onSelect(path);
    } catch (cause) { setError(String(cause)); }
    finally { setBusy(false); }
  };
  return <div className="space-y-1"><div className="flex min-w-0 flex-wrap items-center gap-2">
    <span className="min-w-0 flex-1 break-all rounded border px-3 py-2 text-sm text-muted-foreground" title={value}>{value || placeholder}</span>
    <Button id={id} disabled={busy} variant="secondary" onClick={() => void choose()}>{busy ? "選択中…" : "フォルダーを選択"}</Button>
  </div>{error && <p role="alert" className="text-xs text-destructive">{error}</p>}</div>;
}
