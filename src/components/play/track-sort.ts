/** 一覧の並べ替え。サーバ側 (backend/infra/repositories/track_repository.py) と同じ規則で、
 *  値の無い曲は昇順・降順のどちらでも末尾、文字列は大文字小文字を無視、キーは Camelot 順。 */
export const SORT_FIELDS = ["title", "artist", "bpm", "key", "duration", "genre"] as const;
export type SortField = (typeof SORT_FIELDS)[number];
export type SortState = { field: SortField; direction: "asc" | "desc" } | null;

/** Camelot ホイール順。辞書順だと隣接キーがばらけて選曲に使えない。 */
export const CAMELOT_ORDER: Record<string, number> = {
  "ab minor": 1, "g# minor": 1, "1a": 1, "b major": 2, "1b": 2,
  "eb minor": 3, "d# minor": 3, "2a": 3, "f# major": 4, "gb major": 4, "2b": 4,
  "bb minor": 5, "a# minor": 5, "3a": 5, "db major": 6, "c# major": 6, "3b": 6,
  "f minor": 7, "4a": 7, "ab major": 8, "g# major": 8, "4b": 8,
  "c minor": 9, "5a": 9, "eb major": 10, "d# major": 10, "5b": 10,
  "g minor": 11, "6a": 11, "bb major": 12, "a# major": 12, "6b": 12,
  "d minor": 13, "7a": 13, "f major": 14, "7b": 14,
  "a minor": 15, "8a": 15, "c major": 16, "8b": 16,
  "e minor": 17, "9a": 17, "g major": 18, "9b": 18,
  "b minor": 19, "10a": 19, "d major": 20, "10b": 20,
  "f# minor": 21, "gb minor": 21, "11a": 21, "a major": 22, "11b": 22,
  "c# minor": 23, "db minor": 23, "12a": 23, "e major": 24, "12b": 24,
};

type Sortable = { title?: string | null; artist?: string | null; genre?: string | null; key?: string | null; bpm?: number | null; duration?: number | null };

/** 並べ替えに使う値。null は「値なし」で、向きに関わらず末尾へ送る。 */
function sortValue(track: Sortable, field: SortField): string | number | null {
  // 表記ゆれ（"F Minor" / "f minor"）はサーバ側と同じく吸収する。
  if (field === "key") return CAMELOT_ORDER[(track.key ?? "").trim().toLowerCase()] ?? null;
  if (field === "bpm" || field === "duration") {
    const value = track[field];
    return typeof value === "number" && Number.isFinite(value) && value > 0 ? value : null;
  }
  const text = (track[field] ?? "").trim().toLocaleLowerCase();
  return text || null;
}

/** 次に押したときの状態。同じ列は 昇順 → 降順 → 既定順 と回す。 */
export function nextSort(current: SortState, field: SortField): SortState {
  if (current?.field !== field) return { field, direction: "asc" };
  return current.direction === "asc" ? { field, direction: "desc" } : null;
}

export function sortTracks<T extends Sortable>(tracks: readonly T[], sort: SortState): readonly T[] {
  if (!sort) return tracks;
  const sign = sort.direction === "desc" ? -1 : 1;
  return [...tracks].sort((left, right) => {
    const a = sortValue(left, sort.field), b = sortValue(right, sort.field);
    if (a === null || b === null) return a === b ? 0 : a === null ? 1 : -1;
    if (typeof a === "number" && typeof b === "number") return (a - b) * sign;
    return String(a).localeCompare(String(b)) * sign;
  });
}
