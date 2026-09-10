import { useRef, useState } from "react";
import { Download, Loader2 } from "lucide-react";
import { getErrorDetail } from "@/services/api-client";
import type { RekordboxCueImportSummary } from "@/services/performance-metadata";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";

export function RekordboxCueImportButton({ onImport }: { onImport: () => Promise<RekordboxCueImportSummary> }) {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<RekordboxCueImportSummary | null>(null);
  const [open, setOpen] = useState(false);
  const pending = useRef(false);

  const importCues = async () => {
    if (pending.current) return;
    pending.current = true; setLoading(true); setError(null); setResult(null);
    try { setResult(await onImport()); }
    catch (cause) { setError(getErrorDetail(cause)); }
    finally { pending.current = false; setLoading(false); setOpen(true); }
  };

  return <>
    <button type="button" className="dj-button" disabled={loading} onClick={() => void importCues()}
      title="plumdeckライブラリ全曲のHOT CUE A–Hをrekordboxから一括反映します。対応する曲の保存済みCUEは置き換わります。">
      {loading ? <Loader2 className="animate-spin" aria-hidden /> : <Download aria-hidden />}
      {loading ? "CUE一括反映中…" : "rekordbox CUE一括反映"}
    </button>
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogContent className="max-h-[80vh] overflow-y-auto border-[#34383f] bg-[#202327] text-[#e2e5e9] sm:max-w-lg">
        <DialogHeader><DialogTitle className="text-sm">rekordbox CUE一括反映</DialogTitle>
          <DialogDescription className="text-xs text-[#aeb3bb]">plumdeckに登録済みの全曲が対象です。ファイルパスが一致する曲のHOT CUE A–Hを取り込みます。</DialogDescription></DialogHeader>
        {result && <div role="status" className="space-y-3 text-sm">
          <p>反映 {result.imported.toLocaleString()} 曲 · 対応なし {result.skipped.toLocaleString()} 曲 · 失敗 {result.failed.toLocaleString()} 曲 · 編集競合 {result.conflicts.toLocaleString()} 曲</p>
          <p className="text-xs text-[#aeb3bb]">対応のない曲と編集中に競合した曲は変更していません。</p>
          {result.errors.length > 0 && <ul className="space-y-1 text-xs text-[#efa7a1]">{result.errors.map((item, index) => <li key={`${item.track_id}:${index}`}>曲ID {item.track_id}: {item.message}</li>)}</ul>}
          {result.errors_truncated > 0 && <p className="text-xs text-[#aeb3bb]">ほか {result.errors_truncated.toLocaleString()} 件の詳細は省略しています。</p>}
        </div>}
        {error && <p role="alert" className="text-sm text-[#efa7a1]">{error}</p>}
      </DialogContent>
    </Dialog>
  </>;
}
