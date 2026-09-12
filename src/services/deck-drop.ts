import type { Track } from "../types";
import type { DeckId } from "../types/dj-engine";

export const TRACK_MIME = "application/x-plumdeck-track";
const DROP_SELECTOR = "[data-track-drop-deck]";

export function readDraggedTrack(data: Pick<DataTransfer, "getData"> | null): Track | null {
  try {
    const track = JSON.parse(data?.getData(TRACK_MIME) || "null");
    return track && Number.isSafeInteger(track.id) && track.id > 0
      && typeof track.filepath === "string" && track.filepath.trim()
      && Number.isFinite(track.duration) && track.duration > 0 ? track : null;
  } catch { return null; }
}

/** Only visible deck surfaces opt in. Mixer channels also have data-deck,
 * but must never replace a track when somebody drops on an EQ or fader. */
export function deckDropTarget(node: Element | null): HTMLElement | null {
  const target = node?.closest<HTMLElement>(DROP_SELECTOR);
  return target && /^[ABCD]$/.test(target.dataset.trackDropDeck ?? "") ? target : null;
}

/** Tauri reports physical pixels; elementFromPoint accepts CSS pixels.
 * Never retry unscaled coordinates: that can hit a completely different deck. */
export function nativeDropElement(doc: Pick<Document, "elementFromPoint">, x: number, y: number, scale: number): Element | null {
  if (![x, y, scale].every(Number.isFinite) || scale <= 0) return null;
  return doc.elementFromPoint(x / scale, y / scale);
}

/** One owner for HTML and native notifications of the same library-row drag.
 * Capture on the document covers headers, pads, buttons, jogs and empty space
 * as well as waveforms. Native completion waits briefly for an exact DOM drop. */
export function installDeckDropRouting(doc: Document, load: (deck: DeckId, track: Track) => void) {
  type Session = { track: Track; claimed: boolean };
  let session: Session | null = null;
  let nativeTimer: ReturnType<typeof setTimeout> | undefined;
  let endTimer: ReturnType<typeof setTimeout> | undefined;
  let highlighted: HTMLElement | null = null;

  const highlight = (target: HTMLElement | null) => {
    if (highlighted === target) return;
    highlighted?.removeAttribute("data-track-drop-active");
    highlighted = target;
    highlighted?.setAttribute("data-track-drop-active", "true");
  };
  const clear = () => {
    clearTimeout(nativeTimer); clearTimeout(endTimer);
    session = null;
    highlight(null);
  };
  const end = () => {
    highlight(null);
    clearTimeout(endTimer);
    // Keep a consumed origin marker for a late native notification so it
    // cannot load another deck or be mistaken for an external file import.
    endTimer = setTimeout(clear, 500);
  };
  const targetOf = (event: DragEvent) => event.target instanceof Element ? event.target : null;
  const commit = (current: Session, node: Element | null, otherDrop?: (node: Element | null, track: Track) => void) => {
    if (session !== current || current.claimed) return;
    current.claimed = true;
    highlight(null);
    const target = deckDropTarget(node);
    if (target?.isConnected) load(target.dataset.trackDropDeck as DeckId, current.track);
    else if (!target) otherDrop?.(node, current.track);
  };
  const start = (event: DragEvent) => {
    clear();
    const track = readDraggedTrack(event.dataTransfer);
    if (track) session = { track, claimed: false };
  };
  const over = (event: DragEvent) => {
    if (!session || session.claimed) return;
    const target = deckDropTarget(targetOf(event));
    highlight(target);
    if (target) {
      event.preventDefault();
      if (event.dataTransfer) event.dataTransfer.dropEffect = "copy";
    }
  };
  const drop = (event: DragEvent) => {
    const track = readDraggedTrack(event.dataTransfer);
    if (!track && !session) return;
    // Synthetic drops and drags from another webview can have no dragstart.
    if (!session && track) session = { track, claimed: false };
    if (!session) return;
    const target = targetOf(event);
    clearTimeout(nativeTimer);
    if (deckDropTarget(target)) {
      event.preventDefault();
      event.stopPropagation();
    }
    commit(session, track ? target : null);
    end();
  };
  const escape = (event: KeyboardEvent) => {
    if (event.key !== "Escape" || !session) return;
    session.claimed = true;
    clearTimeout(nativeTimer);
    end();
  };
  // dragstart must bubble AFTER React has written the row's MIME payload.
  doc.addEventListener("dragstart", start);
  doc.addEventListener("dragover", over, true);
  doc.addEventListener("drop", drop, true);
  doc.addEventListener("dragend", end, true);
  doc.addEventListener("keydown", escape, true);

  return {
    current: () => session?.track ?? null,
    hover(node: Element | null) {
      if (session && !session.claimed) highlight(
        deckDropTarget(node),
      );
    },
    leave: () => { highlight(null); },
    drop(node: Element | null, otherDrop?: (node: Element | null, track: Track) => void) {
      const current = session;
      if (!current || current.claimed) return;
      const target = node;
      clearTimeout(nativeTimer);
      // Some webviews send native drop before HTML drop. Let the HTML target
      // settle first; use native coordinates only when no DOM target exists.
      nativeTimer = setTimeout(() => {
        commit(current, target, otherDrop);
        if (session === current) end();
      }, 50);
    },
    dispose() {
      clear();
      doc.removeEventListener("dragstart", start);
      doc.removeEventListener("dragover", over, true);
      doc.removeEventListener("drop", drop, true);
      doc.removeEventListener("dragend", end, true);
      doc.removeEventListener("keydown", escape, true);
    },
  };
}
