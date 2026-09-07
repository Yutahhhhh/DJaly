import { FormEvent, useCallback, useEffect, useRef, useState } from "react";
import {
  AlertCircle,
  ChevronLeft,
  ChevronRight,
  Lightbulb,
  Loader2,
  RefreshCw,
  Search,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { toast } from "@/components/ui/toast";
import { getErrorDetail } from "@/services/api-client";
import {
  WordplayPair,
  WordplayStatus,
  wordplayService,
} from "@/services/wordplay";
import { cn } from "@/lib/utils";
import { WordplayPairCard } from "./WordplayPairCard";

type StatusFilter = WordplayStatus | "all";
const PAGE_SIZE = 20;

const filters: { value: StatusFilter; label: string }[] = [
  { value: "pending", label: "承認待ち" },
  { value: "approved", label: "承認済み" },
  { value: "all", label: "すべて" },
];

export function WordplayView() {
  const [status, setStatus] = useState<StatusFilter>("pending");
  const [queryInput, setQueryInput] = useState("");
  const [query, setQuery] = useState("");
  const [page, setPage] = useState(0);
  const [items, setItems] = useState<WordplayPair[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<number | null>(null);
  const requestSeq = useRef(0);

  const load = useCallback(async (quiet = false) => {
    const seq = ++requestSeq.current;
    if (!quiet) setLoading(true);
    try {
      const result = await wordplayService.list({
        status: status === "all" ? undefined : status,
        query: query || undefined,
        limit: PAGE_SIZE,
        offset: page * PAGE_SIZE,
      });
      if (seq !== requestSeq.current) return;
      setItems(result.items);
      setTotal(result.total);
      setError(null);
    } catch (error) {
      if (seq !== requestSeq.current) return;
      const detail = getErrorDetail(error);
      setError(detail);
      if (!quiet) toast.error("ワードプレイの取得に失敗しました", detail);
    } finally {
      if (seq === requestSeq.current) setLoading(false);
    }
  }, [page, query, status]);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    const timer = window.setInterval(() => load(true), 15_000);
    return () => window.clearInterval(timer);
  }, [load]);

  const changeStatus = (next: StatusFilter) => {
    setStatus(next);
    setPage(0);
  };

  const handleSearch = (event: FormEvent) => {
    event.preventDefault();
    setPage(0);
    setQuery(queryInput.trim());
  };

  const approve = async (pair: WordplayPair) => {
    setBusyId(pair.id);
    try {
      await wordplayService.approve(pair.id);
      toast.success("ワードプレイを承認しました");
      await load(true);
    } catch (error) {
      toast.error("承認に失敗しました", getErrorDetail(error));
    } finally {
      setBusyId(null);
    }
  };

  const toggleVerification = async (pair: WordplayPair) => {
    const nextStatus = pair.verification_status === "tested" ? "unverified" : "tested";
    setBusyId(pair.id);
    try {
      await wordplayService.update(pair.id, { verification_status: nextStatus });
      toast.success(nextStatus === "tested" ? "テスト済みにしました" : "未検証に戻しました");
      await load(true);
    } catch (error) {
      toast.error("検証状態の更新に失敗しました", getErrorDetail(error));
    } finally {
      setBusyId(null);
    }
  };

  const remove = async (pair: WordplayPair) => {
    setBusyId(pair.id);
    try {
      await wordplayService.remove(pair.id);
      toast.success(pair.status === "pending" ? "提案を却下しました" : "ワードプレイを削除しました");
      if (items.length === 1 && page > 0) {
        setPage((current) => current - 1);
      } else {
        await load(true);
      }
    } catch (error) {
      toast.error(pair.status === "pending" ? "却下に失敗しました" : "削除に失敗しました", getErrorDetail(error));
    } finally {
      setBusyId(null);
    }
  };

  const pageCount = Math.max(1, Math.ceil(total / PAGE_SIZE));

  return (
    <div className="flex h-full flex-col overflow-hidden">
      <header className="shrink-0 border-b p-6 pb-4">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <h1 className="text-2xl font-bold tracking-tight">Wordplay</h1>
            <p className="mt-1 text-sm text-muted-foreground">
              MCPクライアントから届いた曲間ワードプレイを確認し、セットリストで再利用する候補を承認します。
            </p>
          </div>
          <Button variant="outline" size="sm" onClick={() => load()} disabled={loading}>
            <RefreshCw className={cn("mr-1.5 h-4 w-4", loading && "animate-spin")} />
            更新
          </Button>
        </div>

        <div className="mt-5 flex flex-wrap items-center gap-3">
          <div className="flex rounded-lg bg-muted p-1" role="group" aria-label="ステータスで絞り込み">
            {filters.map((filter) => (
              <Button
                key={filter.value}
                type="button"
                size="sm"
                variant={status === filter.value ? "secondary" : "ghost"}
                className="h-8"
                onClick={() => changeStatus(filter.value)}
                aria-pressed={status === filter.value}
              >
                {filter.label}
              </Button>
            ))}
          </div>
          <form onSubmit={handleSearch} className="flex min-w-[260px] flex-1 gap-2">
            <div className="relative flex-1">
              <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
              <Input
                value={queryInput}
                onChange={(event) => setQueryInput(event.target.value)}
                placeholder="曲名・アーティスト・キーワードを検索"
                className="pl-9"
                aria-label="ワードプレイを検索"
              />
            </div>
            <Button type="submit" variant="secondary">検索</Button>
          </form>
        </div>
      </header>

      <main className="flex-1 overflow-y-auto p-6">
        {error && (
          <div className="mx-auto mb-4 flex max-w-5xl items-start gap-2 rounded-lg border border-destructive/40 bg-destructive/5 p-3 text-sm text-destructive" role="alert">
            <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
            <span>最新の一覧を取得できませんでした: {error}</span>
          </div>
        )}
        {loading ? (
          <div className="flex h-48 items-center justify-center text-muted-foreground">
            <Loader2 className="mr-2 h-5 w-5 animate-spin" /> 読み込み中
          </div>
        ) : items.length === 0 ? (
          <div className="mx-auto flex max-w-lg flex-col items-center py-20 text-center text-muted-foreground">
            <Lightbulb className="mb-4 h-12 w-12 opacity-25" />
            <p className="font-medium text-foreground">該当するワードプレイはありません</p>
            <p className="mt-2 text-sm leading-relaxed">
              接続済みのMCPクライアントから候補を提案すると、ここに承認待ちとして表示されます。内容を確認して承認すると、セットリストのWordタブから再利用できます。
            </p>
          </div>
        ) : (
          <div className="mx-auto max-w-5xl space-y-3">
            {items.map((pair) => (
              <WordplayPairCard
                key={pair.id}
                pair={pair}
                busy={busyId === pair.id}
                disabled={busyId !== null}
                onApprove={approve}
                onToggleVerification={toggleVerification}
                onRemove={remove}
              />
            ))}
          </div>
        )}
      </main>

      <footer className="flex shrink-0 items-center justify-between border-t px-6 py-3 text-sm text-muted-foreground">
        <span>{total}件中 {total === 0 ? 0 : page * PAGE_SIZE + 1}〜{Math.min((page + 1) * PAGE_SIZE, total)}件</span>
        <div className="flex items-center gap-2">
          <Button variant="outline" size="icon" className="h-8 w-8" onClick={() => setPage((p) => p - 1)} disabled={page === 0 || loading} aria-label="前のページ">
            <ChevronLeft className="h-4 w-4" />
          </Button>
          <span className="min-w-16 text-center">{page + 1} / {pageCount}</span>
          <Button variant="outline" size="icon" className="h-8 w-8" onClick={() => setPage((p) => p + 1)} disabled={page + 1 >= pageCount || loading} aria-label="次のページ">
            <ChevronRight className="h-4 w-4" />
          </Button>
        </div>
      </footer>
    </div>
  );
}
