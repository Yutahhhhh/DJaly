type DeckIdentity = { slot: number; loaded: boolean; title: string | null; artist: string | null };

/** Tempo, pitch, key display and native signatures can change without loading a song. */
export function observedDeckIdentity(decks: readonly DeckIdentity[]): string {
  return JSON.stringify([...decks].sort((a, b) => a.slot - b.slot).map(deck => [
    deck.slot, deck.loaded,
    deck.loaded ? deck.title?.normalize("NFC").trim() ?? "" : "",
    deck.loaded ? deck.artist?.normalize("NFC").trim() ?? "" : "",
  ]));
}

/** Keeps a successful match visible during same-song verification. */
export class DeckResolutionCache<T> {
  private identity: string | null = null;
  value: T | null = null;

  observe(decks: readonly DeckIdentity[]): string {
    const identity = observedDeckIdentity(decks);
    if (identity !== this.identity) this.value = null;
    this.identity = identity;
    return identity;
  }

  publish(value: T): void { this.value = value; }
  clear(): void { this.identity = null; this.value = null; }
}
