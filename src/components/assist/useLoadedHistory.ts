import { useEffect, useState, type MutableRefObject } from "react";
import type { ResolvedDeck } from "@/services/assist";
import { HISTORY_STORAGE_KEY, mergeLoadedIds, parseLoadedHistory, resolvedLoadedIds } from "./loaded-history";

export function useLoadedHistory(decks: ResolvedDeck[], dragging: boolean, freeze: MutableRefObject<boolean>) {
  const [initial] = useState(() => {
    try { return { ids: parseLoadedHistory(localStorage.getItem(HISTORY_STORAGE_KEY)), message: null as string | null }; }
    catch { return { ids: [] as number[], message: "履歴を読み込めませんでした。現在のロード曲から記録します。" }; }
  });
  const [ids, setIds] = useState(initial.ids);
  const [message, setMessage] = useState(initial.message);
  const current = resolvedLoadedIds(decks);
  const currentKey = current.join(",");
  useEffect(() => {
    if (freeze.current || dragging) return;
    setIds(previous => {
      const next = mergeLoadedIds(previous, currentKey ? currentKey.split(",").map(Number) : []);
      return next.join(",") === previous.join(",") ? previous : next;
    });
  }, [currentKey, dragging, freeze]);
  useEffect(() => {
    if (freeze.current || dragging) return;
    try { localStorage.setItem(HISTORY_STORAGE_KEY, JSON.stringify(ids)); }
    catch { setMessage("履歴を保存できません。この画面を閉じると履歴が失われる場合があります。"); }
  }, [ids, dragging, freeze]);
  const reset = () => {
    if (freeze.current) return;
    setIds(current);
    setMessage(`履歴をリセットしました。現在ロード中の ${current.length} 曲は引き続き除外します。`);
  };
  return { excludedIds: mergeLoadedIds(ids, current), message, reset };
}
