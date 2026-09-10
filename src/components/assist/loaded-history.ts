export const HISTORY_STORAGE_KEY = "plumdeck.assist.loaded-history.v1";
export const MAX_EXCLUDED_TRACKS = 10_000;

type ObservedDeck = { status: string; track: { id: number } | null };
const validId = (value: unknown): value is number => typeof value === "number" && Number.isSafeInteger(value) && value > 0;

export function mergeLoadedIds(previous: readonly number[], incoming: readonly number[]): number[] {
  return [...new Set([...previous, ...incoming].filter(validId))].sort((a, b) => a - b);
}

/** Only library identities positively resolved from a deck are eligible. */
export function resolvedLoadedIds(decks: readonly ObservedDeck[]): number[] {
  return mergeLoadedIds([], decks.flatMap(deck => deck.status === "resolved" && deck.track ? [deck.track.id] : []));
}

export function parseLoadedHistory(raw: string | null): number[] {
  if (!raw) return [];
  const value: unknown = JSON.parse(raw);
  if (!Array.isArray(value) || !value.every(validId)) throw new Error("Invalid loaded history");
  return mergeLoadedIds([], value);
}
