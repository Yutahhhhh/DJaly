import { useEffect, useState } from "react";
import { useImportQueue, importFinished } from "@/hooks/useImportQueue";
import { workflowsService, type ImportBatch } from "@/services/workflows";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";

const labels: Record<string, string> = {
  queued: "待機中", running: "解析中", processing: "解析中", paused: "一時停止",
  completed: "完了", completed_with_errors: "エラーあり", canceled: "キャンセル",
};
export function ImportQueueProgress({ raised = false }: { raised?: boolean }) {
  const { batches, error } = useImportQueue();
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, []);
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [actionError, setActionError] = useState("");
  const [details, setDetails] = useState<ImportBatch | null>(null);
  const [dismissed, setDismissed] = useState<Set<string>>(() => new Set());
  const active = batches.filter(row => !importFinished(row));
  const recentCutoff = Date.now() - 60 * 60 * 1000;
  const failures = batches.filter(row => row.state === "completed_with_errors" && !dismissed.has(row.id) &&
    (!row.updated_at || Date.parse(row.updated_at) >= recentCutoff));
  const display = [...active, ...failures.filter(row => !active.some(item => item.id === row.id))];
  const remaining = active.filter(row => row.state !== "paused").reduce((sum, row) => sum + Math.max(0,
    Number(row.total_items) - Number(row.succeeded_items) - Number(row.failed_items) - Number(row.skipped_items)), 0);
  const failed = failures.reduce((sum, row) => sum + Number(row.failed_items), 0);
  const title = remaining ? `${remaining}曲の解析が進行中（待機含む）`
    : active.some(row => row.state !== "paused") ? "解析の完了処理中"
    : active.length ? "解析キューは一時停止中" : failed ? `解析キュー・失敗 ${failed}曲` : "解析キュー";
  const control = async (id: string, action: "pause" | "resume" | "cancel" | "retry") => {
    setBusy(id); setActionError("");
    try {
      await workflowsService.controlImport(id, action);
      if (action === "retry") setDismissed(current => {
        const next = new Set(current); next.delete(id); return next;
      });
      window.dispatchEvent(new Event("plumdeck:imports-changed"));
    }
    catch (cause) { setActionError(String(cause)); }
    finally { setBusy(null); }
  };
  const inspect = async (id: string) => {
    setBusy(id); setActionError("");
    try { setDetails(await workflowsService.importStatus(id)); }
    catch (cause) { setActionError(String(cause)); }
    finally { setBusy(null); }
  };
  if (!display.length && !error) return null;
  const setDialogOpen = (next: boolean) => {
    setOpen(next);
    if (!next && failures.length) {
      setDismissed(current => new Set([...current, ...failures.map(row => row.id)]));
    }
  };
  return <>
    <Button variant="outline" onClick={() => setOpen(true)}
      className={`fixed right-6 z-50 max-w-[calc(100vw-3rem)] rounded-full bg-background text-foreground shadow-lg ${raised ? "bottom-24" : "bottom-6"}`}>
      <span className="truncate">{error ? "解析キュー・再接続中" : title}</span>
    </Button>
    <Dialog open={open} onOpenChange={setDialogOpen}>
      <DialogContent className="max-h-[85vh] overflow-y-auto sm:max-w-xl">
        <DialogHeader><DialogTitle>解析・取り込みキュー</DialogTitle>
          <DialogDescription>画面の切り替えや再読み込み後も、保存済みのジョブから進捗を表示します。</DialogDescription>
        </DialogHeader>
        {(error || actionError) && <p role="alert" className="text-sm text-destructive">{actionError || error}</p>}
        {display.map(row => {
          const done = Number(row.succeeded_items) + Number(row.failed_items) + Number(row.skipped_items);
          const effectiveProfile = row.effective_analysis_profile || (row.analysis_profile === "light" ? "light" : "full");
          return <section key={row.id} className="min-w-0 space-y-2 rounded border p-3 text-sm">
            <div className="flex flex-wrap justify-between gap-2">
              <strong>{row.target_name_snapshot || "Collection"}</strong><span>{labels[row.state] || row.state} · {done}/{row.total_items}曲</span>
            </div>
            <Progress value={Number(row.total_items) ? 100 * done / Number(row.total_items) : 0} />
            {row.current_file && <p className="truncate" title={row.current_file}>{row.current_file.split(/[/\\]/).pop()}</p>}
            {row.progress && !importFinished(row) && row.state !== "paused" && <p role="status" className="text-xs">
              {row.progress.label} · {Math.max(0, Math.floor(now / 1000 - row.progress.started_at))}秒
            </p>}
            <p className="text-xs text-muted-foreground">
              解析方法：{effectiveProfile === "light" ? "軽量（プレイ優先）" : row.analysis_profile === "auto" ? "自動・詳細解析中" : "詳細"}
            </p>
            <p className="text-xs text-muted-foreground">成功 {row.succeeded_items} · 失敗 {row.failed_items} · スキップ {row.skipped_items} · 待機 {row.queued_items ?? 0}</p>
            <div className="flex flex-wrap gap-2">
              {!importFinished(row) && <>
                <Button size="sm" disabled={busy !== null} onClick={() => void control(row.id, row.state === "paused" ? "resume" : "pause")}>{row.state === "paused" ? "再開" : "一時停止"}</Button>
                <Button size="sm" variant="outline" disabled={busy !== null} onClick={() => void control(row.id, "cancel")}>キャンセル</Button>
              </>}
              {row.state === "completed_with_errors" && <Button size="sm" disabled={busy !== null} onClick={() => void control(row.id, "retry")}>失敗分を再試行</Button>}
              <Button size="sm" variant="outline" disabled={busy !== null} onClick={() => void inspect(row.id)}>詳細</Button>
            </div>
            {details?.id === row.id && <ul className="max-h-48 space-y-1 overflow-y-auto text-xs">
              {details.items?.map(item => <li key={String(item.id)} className="break-all">
                {String(item.canonical_path ?? "").split(/[/\\]/).pop()} · {item.analysis_level === "light" ? "軽量解析で使用可能" : String(item.error_message || item.state)}
              </li>)}
            </ul>}
          </section>;
        })}
      </DialogContent>
    </Dialog>
  </>;
}
