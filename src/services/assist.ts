import { invoke, isTauri } from "@tauri-apps/api/core";
import { apiClient } from "./api-client";
import type { Track } from "@/types";

export type AssistIntent = "groove" | "shift" | "wordplay";
export type GenreScope = "any" | "same_genre" | "same_subgenre";
export type EnergyDirection = "up" | "hold" | "down";
export type ReasonTone = "good" | "neutral" | "caution";
export type DeckStatus = "empty" | "resolved" | "ambiguous" | "unresolved" | "not_in_library";
export type MatchConfidence = "title_and_artist" | "title_only";

/** One deck exactly as rekordbox is drawing it. Never an identity on its own. */
export interface DeckObservation {
  slot: number;
  loaded: boolean;
  title: string | null;
  artist: string | null;
  track_bpm: number | null;
  tempo_bpm: number | null;
  display_key: string | null;
}

export interface AssistSnapshot {
  supported: boolean;
  permission_granted: boolean;
  app_running: boolean;
  app_path: string | null;
  layout_hint: string | null;
  decks: DeckObservation[];
  open_audio_paths: string[];
  open_paths_error: string | null;
  signature: string;
  captured_at_ms: number;
  unavailable_reason: string | null;
  warnings: string[];
}

export interface AmbiguousCandidate {
  rekordbox_id: string;
  filepath: string;
  title: string;
  artist: string;
}

export interface ResolvedDeck {
  slot: number;
  status: DeckStatus;
  observed: Omit<DeckObservation, "slot" | "loaded">;
  track: Track | null;
  rekordbox_id: string | null;
  filepath: string | null;
  match_confidence: MatchConfidence | null;
  candidates: AmbiguousCandidate[];
  message: string | null;
}

export interface DeckResolution {
  decks: ResolvedDeck[];
  library_error: string | null;
  inspected_paths: number;
}

export interface AssistReason {
  kind: string;
  tone: ReasonTone;
  text: string;
}

export interface AssistWordplay {
  pair_id: number;
  keyword: string;
  source_phrase: string;
  target_phrase: string;
  transition_notes: string;
  evidence_type: string;
  verification_status: string;
}

export interface AssistCandidate extends Track {
  score: number;
  components: Record<string, number>;
  reasons: AssistReason[];
  wordplay: AssistWordplay | null;
}

export interface AssistRecommendations {
  intent: AssistIntent;
  energy_direction: EnergyDirection;
  source_track_id: number;
  candidates: AssistCandidate[];
  notes: string[];
  unavailable_originals: number;
}

export interface CompactWindowResult {
  applied: boolean;
  message: string | null;
}

/** Snapshot used when there is no desktop shell to read rekordbox with. */
export const UNAVAILABLE_SNAPSHOT: AssistSnapshot = {
  supported: false,
  permission_granted: false,
  app_running: false,
  app_path: null,
  layout_hint: null,
  decks: [],
  open_audio_paths: [],
  open_paths_error: null,
  signature: "",
  captured_at_ms: 0,
  unavailable_reason:
    "デッキの読み取りは Djaly デスクトップアプリでのみ動作します（ブラウザプレビューでは無効）",
  warnings: [],
};

export const isDesktopShell = () => isTauri();

export const assistService = {
  /** Reads the decks rekordbox currently has loaded. Read-only. */
  async snapshot(): Promise<AssistSnapshot> {
    if (!isDesktopShell()) return UNAVAILABLE_SNAPSHOT;
    return invoke<AssistSnapshot>("assist_snapshot");
  },

  /** Shows the macOS accessibility prompt. Only call from a user gesture. */
  async requestAccessibility(): Promise<boolean> {
    if (!isDesktopShell()) return false;
    return invoke<boolean>("assist_request_accessibility");
  },

  async openAccessibilitySettings(): Promise<void> {
    if (!isDesktopShell()) return;
    await invoke("assist_open_accessibility_settings");
  },

  async enterCompactWindow(width: number, height: number): Promise<CompactWindowResult> {
    if (!isDesktopShell()) return { applied: false, message: null };
    return invoke<CompactWindowResult>("assist_enter_compact_window", { width, height });
  },

  async exitCompactWindow(): Promise<CompactWindowResult> {
    if (!isDesktopShell()) return { applied: false, message: null };
    return invoke<CompactWindowResult>("assist_exit_compact_window");
  },

  async setAlwaysOnTop(enabled: boolean): Promise<void> {
    if (!isDesktopShell()) return;
    await invoke("assist_set_always_on_top", { enabled });
  },

  libraryStatus: () =>
    apiClient.get<{ available: boolean; message: string | null; registered_tracks: number }>(
      "/assist/library-status",
    ),

  resolveDecks: (decks: DeckObservation[], openAudioPaths: string[]) =>
    apiClient.post<DeckResolution>("/assist/decks/resolve", {
      decks,
      open_audio_paths: openAudioPaths,
    }, 30_000),

  recommendations: (params: {
    sourceTrackId: number;
    intent: AssistIntent;
    energyDirection: EnergyDirection;
    genreScope?: GenreScope;
    limit?: number;
    excludeTrackIds?: number[];
  }) =>
    apiClient.post<AssistRecommendations>("/assist/recommendations", {
      source_track_id: params.sourceTrackId,
      intent: params.intent,
      energy_direction: params.energyDirection,
      genre_scope: params.genreScope ?? "any",
      limit: params.limit ?? 12,
      exclude_track_ids: params.excludeTrackIds ?? [],
    }, 60_000),
};
