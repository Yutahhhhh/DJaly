import { useEffect, useRef, useState } from "react";
import { GripVertical, Pin, PinOff, RefreshCw, Sparkles } from "lucide-react";
import { cn } from "@/lib/utils";
import { assistService, type AssistCandidate, type AssistIntent, type AssistRecommendations, type EnergyDirection, type GenreScope } from "@/services/assist";
import { getErrorDetail } from "@/services/api-client";
import { useCompactWindow } from "./useCompactWindow";
import { useRekordboxDecks } from "./useRekordboxDecks";
import { StatusBanner } from "./StatusBanner";
import { canDragOut, startFileDrag } from "./native-drag";

import { useLoadedHistory } from "./useLoadedHistory";
import { MAX_EXCLUDED_TRACKS } from "./loaded-history";

const intents: { value: AssistIntent; label: string; detail: string }[] = [
  { value: "groove", label: "グルーヴ", detail: "流れをつなぐ" },
  { value: "shift", label: "展開", detail: "雰囲気を変える" },
  { value: "wordplay", label: "ワードプレイ", detail: "言葉でつなぐ" },
];

function primaryReasons(track: AssistCandidate, intent: AssistIntent) {
  const priority = intent === "wordplay" ? ["wordplay", "tempo"] : intent === "shift" ? ["genre", "energy", "tempo"] : ["tempo", "similarity", "energy"];
  return priority.flatMap(kind => {
    const reason = track.reasons.find(item => item.kind === kind);
    if (!reason) return [];
    let text = reason.text;
    if (kind === "wordplay" && track.wordplay) {
      text = `「${track.wordplay.keyword}」でつなぐ · ${track.wordplay.verification_status === "tested" ? "試聴済み" : "試聴未確認"}`;
    } else if (kind === "similarity") {
      text = reason.tone === "caution" ? "音色比較なし" : "曲全体の音色傾向が近い";
    } else if (kind === "energy") {
      text = text.replace(/（.*$/, "").replace("エナジー", "エネルギー");
      if (reason.tone === "caution" && !text.includes("→")) text = "エネルギー情報なし";
    } else if (kind === "tempo") {
      text = text.replace("（ハーフ/ダブルテンポ換算）", " · 倍速換算");
      if (!text.includes("→")) text = "テンポ情報なし";
    }
    return [{ ...reason, text }];
  }).slice(0, 2);
}

export function AssistWorkspace() {
  const compact = useCompactWindow(true);
  const freeze = useRef(false);
  const dragPointer = useRef<{ id: number; x: number; y: number } | null>(null);
  const [dragging, setDragging] = useState(false);
  const decks = useRekordboxDecks(true, dragging, freeze);
  const [slot, setSlot] = useState(1);
  const [intent, setIntent] = useState<AssistIntent>("groove");
  const [genreScope, setGenreScope] = useState<GenreScope>("any");
  const [resultKey, setResultKey] = useState("");
  const history = useLoadedHistory(decks.decks, dragging, freeze);
  const [energy, setEnergy] = useState<EnergyDirection>("hold");
  const [result, setResult] = useState<AssistRecommendations | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [dragMessage, setDragMessage] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [revision, setRevision] = useState(0);
  const generation = useRef(0);
  const selected = decks.decks.find(deck => deck.slot === slot);
  const sourceId = selected?.status === "resolved" ? selected.track?.id : undefined;
  const excluded = history.excludedIds.join(",");
  const historyFull = history.excludedIds.length > MAX_EXCLUDED_TRACKS;
  const requestKey = JSON.stringify([sourceId, intent, energy, genreScope, excluded, revision]);

  useEffect(() => {
    const current = ++generation.current;
    if (freeze.current) return;
    setError(null);
    setBusy(false);
    if (!sourceId || historyFull) { setResult(null); return; }
    // visibleResult already hides changed requests; retain same-request results
    // while rechecking after a drag, so the list never flashes empty.
    setBusy(true);
    void assistService.recommendations({ sourceTrackId: sourceId, intent, energyDirection: energy, genreScope, excludeTrackIds: excluded.split(",").filter(Boolean).map(Number), limit: 8 })
      .then(value => { if (generation.current === current && !freeze.current) { setResult(value); setResultKey(requestKey); } })
      .catch(failure => { if (generation.current === current && !freeze.current) { setResult(null); setError(getErrorDetail(failure)); } })
      .finally(() => { if (generation.current === current && !freeze.current) setBusy(false); });
    return () => { generation.current += 1; };
  }, [sourceId, intent, energy, genreScope, excluded, revision, dragging, historyFull, requestKey]);

  const refresh = () => {
    if (freeze.current) return;
    generation.current += 1;
    setResult(null);
    decks.refresh();
    setRevision(value => value + 1);
  };
  const drag = async (filepath: string, label: string) => {
    if (freeze.current) return;
    freeze.current = true;
    generation.current += 1;
    setDragging(true);
    setDragMessage(null);
    try {
      const outcome = await startFileDrag(filepath, label);
      setDragMessage(outcome.message ?? null);
    } finally {
      decks.refresh();
      freeze.current = false;
      setDragging(false);
    }
  };
  const slots = Array.from(new Set([1, 2, ...(decks.snapshot?.decks.map(deck => deck.slot) ?? [])])).sort();
  const observations = decks.snapshot?.decks ?? [];
  const observed = observations.find(deck => deck.slot === slot);
  const sourceTitle = selected?.track?.title ?? observed?.title;
  const sourceArtist = selected?.track?.artist ?? observed?.artist;
  const visibleResult = resultKey === requestKey && sourceId && result?.source_track_id === sourceId && result.intent === intent && result.energy_direction === energy ? result : null;

  return (
    <main className="flex h-full min-h-0 w-full flex-col bg-[#0c1018] text-slate-100">
      <div className="flex shrink-0 items-center justify-between border-b border-white/5 px-4 py-2">
        <div><div className="flex items-center gap-2 text-sm font-semibold"><Sparkles className="size-4 text-amber-300" /> 次の一曲</div></div>
        <div className="flex gap-1">
          <button
            type="button"
            aria-label={compact.alwaysOnTop ? "ウィンドウの固定を解除" : "ウィンドウを最前面に固定"}
            aria-pressed={compact.alwaysOnTop}
            title={compact.alwaysOnTop ? "最前面の固定を解除します" : "他のウィンドウより手前に表示します"}
            disabled={!compact.supported || dragging}
            onClick={() => compact.setAlwaysOnTop(!compact.alwaysOnTop)}
            className={cn("flex items-center gap-1.5 rounded-md border px-2.5 py-1.5 text-[11px] font-medium disabled:opacity-30", compact.alwaysOnTop ? "border-amber-300/40 bg-amber-300/10 text-amber-300" : "border-slate-700 text-slate-400 hover:bg-white/5")}
          >
            {compact.alwaysOnTop ? <PinOff className="size-3.5" /> : <Pin className="size-3.5" />}
            {compact.alwaysOnTop ? "固定解除" : "最前面に固定"}
          </button>
          <button type="button" aria-label="再読み込み" title="再読み込み" disabled={dragging} onClick={refresh} className="rounded-md p-2 text-slate-400 hover:bg-white/5 disabled:opacity-30"><RefreshCw className={cn("size-4", busy && "animate-spin")} /></button>
        </div>
      </div>
      <div className="min-h-0 flex-1 space-y-2 overflow-y-auto px-3 py-2">
        <fieldset disabled={dragging}><StatusBanner snapshot={decks.snapshot} libraryError={decks.resolution?.library_error ?? null} readError={decks.error} windowMessage={compact.message} onRefresh={refresh} /></fieldset>
        <section aria-label="基準デッキ" className="rounded-xl border border-white/10 bg-white/[0.025] p-2.5">
          <div className="mb-1 flex items-center justify-between"><span className="text-[10px] text-slate-400">基準デッキ</span><div className="flex gap-1">{slots.map(value => <button type="button" key={value} disabled={dragging} aria-pressed={slot === value} onClick={() => setSlot(value)} className={cn("rounded px-3 py-1 text-xs transition-colors disabled:opacity-50", slot === value ? "bg-amber-300 text-slate-950" : "bg-white/5 text-slate-400 hover:bg-white/10")}>{value}</button>)}</div></div>
          <p className="truncate text-sm font-semibold">{sourceTitle || (decks.loading ? "デッキを確認中…" : "曲が読み込まれていません")}</p>
          <div className="mt-1 flex items-center justify-between gap-2"><p className="truncate text-[11px] text-slate-400">{sourceArtist || "—"}</p>
          {sourceTitle && <p className="shrink-0 text-[10px] tabular-nums text-slate-400">{observed?.tempo_bpm ?? observed?.track_bpm ?? selected?.track?.bpm ?? "—"} BPM <span className="mx-2 text-slate-700">/</span>{observed?.display_key ?? selected?.track?.key ?? "—"}</p>}</div>
          {selected?.message && <p className="mt-2 text-[11px] text-amber-200">{selected.message}</p>}
          {!sourceId && sourceTitle && !selected && <p className="mt-2 text-[11px] text-slate-500">ライブラリの曲と照合中…</p>}
        </section>
        <fieldset disabled={dragging} className="space-y-2">
          <legend className="mb-1 text-[10px] text-slate-400">どうつなぐ？</legend>
          <div className="grid grid-cols-3 gap-1.5">{intents.map(item => <button type="button" key={item.value} aria-pressed={intent === item.value} onClick={() => setIntent(item.value)} className={cn("rounded-lg border px-1 py-1.5 text-center", intent === item.value ? "border-amber-300/50 bg-amber-300/10 text-amber-200" : "border-white/10 text-slate-400 hover:bg-white/5")}><span className="block text-xs font-medium">{item.label}</span><span className="mt-0.5 block text-[9px] opacity-70">{item.detail}</span></button>)}</div>
          <div className="flex items-center justify-between"><span className="text-[10px] text-slate-500">エネルギー</span><div className="flex rounded-md bg-white/5 p-0.5">{([{ value: "down", label: "↓ 抑える" }, { value: "hold", label: "→ 保つ" }, { value: "up", label: "↑ 上げる" }] as const).map(item => <button type="button" key={item.value} aria-pressed={energy === item.value} onClick={() => setEnergy(item.value)} className={cn("rounded px-2 py-1 text-[10px]", energy === item.value ? "bg-slate-700 text-white" : "text-slate-500")}>{item.label}</button>)}</div></div>
          <div className="flex items-center justify-between"><label htmlFor="assist-genre" className="text-[10px] text-slate-500">ジャンル</label><select id="assist-genre" value={genreScope} onChange={event => { generation.current += 1; setResult(null); setGenreScope(event.target.value as GenreScope); }} className="rounded border border-slate-700 bg-slate-900 px-2 py-1 text-[10px] text-slate-300"><option value="any">指定なし</option><option value="same_genre">同一ジャンル</option><option value="same_subgenre">同一サブジャンル</option></select></div>
        </fieldset>
        <div className="flex items-center justify-between text-[10px]"><span className="text-slate-500">ロード済み {history.excludedIds.length}曲を除外</span><button type="button" disabled={dragging} onClick={() => { if (freeze.current) return; generation.current += 1; setResult(null); history.reset(); setRevision(value => value + 1); }} className="text-slate-400 underline underline-offset-2 hover:text-slate-200 disabled:opacity-40">履歴をリセット</button></div>
        {history.message && <p role="status" className="text-[10px] text-slate-400">{history.message}</p>}
        {historyFull && <p role="alert" className="text-[11px] text-amber-200">除外履歴が10,000曲を超えました。おすすめを再開するには履歴をリセットしてください。</p>}
        <section aria-label="おすすめの曲" aria-busy={busy} className="space-y-2">
          <div className="flex justify-between text-[10px] text-slate-500"><span>おすすめ {visibleResult ? `· ${visibleResult.candidates.length}` : ""}</span><span>{dragging ? "ドラッグ中 · 候補を固定" : "曲をデッキの曲名へドラッグ"}</span></div>
          {error && <p role="alert" className="rounded-lg bg-rose-950/40 p-3 text-xs text-rose-200">おすすめを取得できませんでした。再読み込みでお試しください。<span className="mt-1 block text-[10px] opacity-70">{error}</span></p>}
          {dragMessage && <p role="status" className="text-xs text-amber-200">{dragMessage}</p>}
          {busy && !visibleResult && <p className="py-6 text-center text-xs text-slate-500">次の一曲を探しています…</p>}
          {!busy && !error && !sourceId && <p className="py-5 text-center text-xs text-slate-500">基準デッキの曲が確認できると、候補が表示されます。</p>}
          {visibleResult?.candidates.map((track, index) => <article key={track.id} draggable={false}
            onPointerDown={event => {
              if (!canDragOut() || freeze.current || event.button !== 0 || event.pointerType !== "mouse" || (event.target as Element).closest("button, a, input, summary, details")) return;
              event.preventDefault();
              dragPointer.current = { id: event.pointerId, x: event.clientX, y: event.clientY };
              event.currentTarget.setPointerCapture(event.pointerId);
            }}
            onPointerMove={event => {
              const pointer = dragPointer.current;
              if (!pointer || pointer.id !== event.pointerId) return;
              if (!(event.buttons & 1)) { dragPointer.current = null; return; }
              if (Math.hypot(event.clientX - pointer.x, event.clientY - pointer.y) < 5) return;
              dragPointer.current = null;
              event.currentTarget.releasePointerCapture(event.pointerId);
              // Use a native gesture directly, avoiding a competing HTML drag session.
              void drag(track.filepath, `${track.artist} — ${track.title}`);
            }}
            onPointerUp={() => { dragPointer.current = null; }}
            onPointerCancel={() => { dragPointer.current = null; }}
            onLostPointerCapture={() => { dragPointer.current = null; }}
            onDragStart={event => event.preventDefault()} className={cn("group flex select-none gap-2 rounded-lg border border-white/10 bg-white/[0.025] px-2.5 py-2", canDragOut() && "cursor-grab hover:border-amber-300/30 active:cursor-grabbing")}>
            <span className="pt-0.5 text-[10px] tabular-nums text-slate-600">{String(index + 1).padStart(2, "0")}</span>
            <div className="min-w-0 flex-1">
              <div className="flex items-baseline justify-between gap-2"><p className="truncate text-xs font-medium" title={track.title}>{track.title}</p><span className="shrink-0 text-[10px] tabular-nums text-amber-200/80">{track.bpm || "—"} · {track.key || "—"}</span></div>
              <p className="truncate text-[10px] text-slate-400">{track.artist}</p>
              <div className="mt-1 flex flex-wrap gap-x-2 text-[10px] leading-snug">{primaryReasons(track, intent).map(reason => <span key={reason.kind} className={cn("max-w-full truncate", reason.tone === "caution" ? "text-amber-300/80" : "text-slate-400")}>{reason.text}</span>)}</div>
              <details className="mt-0.5 text-[10px]" onClick={event => { event.stopPropagation(); if (dragging) event.preventDefault(); }}>
                <summary className="w-fit cursor-pointer text-slate-500 hover:text-slate-300">詳しく</summary>
                <div className="space-y-1 pt-1.5">{track.reasons.map((reason, i) => <p key={i} className={cn("leading-relaxed", reason.tone === "caution" ? "text-amber-300/80" : "text-slate-400")}>{reason.text}</p>)}{track.wordplay?.transition_notes && <p className="text-violet-300">{track.wordplay.transition_notes}</p>}</div>
              </details>
            </div>
            <GripVertical className="mt-1 size-3.5 shrink-0 text-slate-600" />
          </article>)}
          {visibleResult && !visibleResult.candidates.length && <p className="py-4 text-center text-xs text-slate-400">条件に合う曲がありません。つなぎ方を変えてお試しください。</p>}
          {visibleResult?.notes.map((note, i) => <p key={i} className="text-[10px] leading-relaxed text-slate-500">{note}</p>)}
        </section>
      </div>
    </main>
  );
}
