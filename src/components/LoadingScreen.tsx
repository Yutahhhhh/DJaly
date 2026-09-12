import { CheckCircle2, Loader2 } from "lucide-react";
import { isTauri } from "@tauri-apps/api/core";
import type { StartupProgress } from "@/hooks/useStartupProgress";
import { Button } from "@/components/ui/button";

export function LoadingScreen({ progress, seconds, connectionError, onRetry }: {
  progress: StartupProgress; seconds: number; connectionError: string; onRetry: () => void;
}) {
  const steps = ["解析サービスの起動", "設定・保存先の読み込み", "ライブラリ・解析・再生機能の準備", "楽曲データベースの準備", "前回の取り込み状態の復元"];
  return (
    <div className="flex min-h-screen w-screen flex-col items-center justify-center bg-background text-foreground p-6 space-y-6">
      <div className="relative flex flex-col items-center">
        <div className="relative h-24 w-24 mb-6 flex items-center justify-center">
          <img 
            src="/plumdeck-logo.png"
            alt="plumdeck logo"
            className="h-24 w-24 object-contain"
          />
        </div>
        
        <div className="flex w-full max-w-md flex-col items-center space-y-4" role="status" aria-live="polite">
          <div className="flex items-center space-x-2 text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" />
            <p className="text-sm font-medium">{progress.label}</p>
          </div>
          <p className="text-xs text-muted-foreground">経過 {Math.floor(seconds / 60)}分{seconds % 60}秒{isTauri() ? ` · ${progress.completed}/${progress.total}工程完了` : ""}</p>
          {isTauri() && <ol className="w-full space-y-2 text-left text-sm">
            {steps.map((label, index) => <li key={label} className={`flex items-center gap-2 ${index < progress.completed ? "text-green-600" : index === progress.completed ? "text-foreground" : "text-muted-foreground"}`}>
              {index < progress.completed ? <CheckCircle2 className="h-4 w-4" /> : index === progress.completed ? <Loader2 className="h-4 w-4 animate-spin" /> : <span className="w-4 text-center">·</span>}
              {label}
            </li>)}
          </ol>}
          {(progress.error || seconds >= 30) && <div className="w-full space-y-3 rounded border p-3 text-sm">
            <p role={progress.error ? "alert" : undefined}>{progress.error || "準備に時間がかかっています。上に表示した工程の完了を待っています。"}</p>
            {connectionError && <p className="break-words text-xs text-muted-foreground">{connectionError}</p>}
            <Button variant="outline" size="sm" onClick={onRetry}>接続を再確認</Button>
          </div>}
        </div>
      </div>
    </div>
  );
}
