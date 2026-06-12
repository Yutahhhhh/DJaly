import { FilterState } from "@/components/music-library/types";
import { Track } from "@/types";

// --- Camelot Wheel (Harmonic Mixing) ---
// backend/utils/audio_math.py の KEY_TO_CAMELOT / CAMELOT_ADJACENCY と対応

const KEY_TO_CAMELOT: Record<string, string> = {
  "C Major": "8B", "C Minor": "5A",
  "C# Major": "3B", "Db Major": "3B", "C# Minor": "12A",
  "D Major": "10B", "D Minor": "7A",
  "D# Major": "5B", "Eb Major": "5B", "D# Minor": "2A", "Eb Minor": "2A",
  "E Major": "12B", "E Minor": "9A",
  "F Major": "7B", "F Minor": "4A",
  "F# Major": "2B", "Gb Major": "2B", "F# Minor": "11A",
  "G Major": "9B", "G Minor": "6A",
  "G# Major": "4B", "Ab Major": "4B", "G# Minor": "1A",
  "A Major": "11B", "A Minor": "8A",
  "A# Major": "6B", "Bb Major": "6B", "A# Minor": "3A", "Bb Minor": "3A",
  "B Major": "1B", "B Minor": "10A",
};

function normalizeKeyToCamelot(key?: string | null): string | null {
  if (!key) return null;
  const trimmed = key.trim();
  if (/^\d{1,2}[AB]$/.test(trimmed)) return trimmed;
  if (KEY_TO_CAMELOT[trimmed]) return KEY_TO_CAMELOT[trimmed];
  const found = Object.keys(KEY_TO_CAMELOT).find((k) =>
    trimmed.toLowerCase().includes(k.toLowerCase())
  );
  return found ? KEY_TO_CAMELOT[found] : null;
}

export type KeyCompatibility = "perfect" | "compatible" | "clash" | "unknown";

/** 前曲とのキー相性を Camelot Wheel の隣接関係で判定する */
export function getKeyCompatibility(
  fromKey?: string | null,
  toKey?: string | null
): KeyCompatibility {
  const a = normalizeKeyToCamelot(fromKey);
  const b = normalizeKeyToCamelot(toKey);
  if (!a || !b) return "unknown";
  if (a === b) return "perfect";

  const num = (c: string) => parseInt(c.slice(0, -1), 10);
  const letter = (c: string) => c.slice(-1);

  // 同番号の A/B 切替、または ±1 (12↔1 のラップあり) で同レターは相性良
  if (num(a) === num(b)) return "compatible";
  const diff = Math.abs(num(a) - num(b));
  if ((diff === 1 || diff === 11) && letter(a) === letter(b)) return "compatible";
  return "clash";
}

/** 前曲との遷移情報 (BPM 差・キー相性) を返す。生成結果リストの根拠表示用。 */
export function getTransitionInfo(
  prev: Track | null | undefined,
  next: Track
): { bpmDiff: number | null; keyCompat: KeyCompatibility } {
  const bpmDiff =
    prev?.bpm && next.bpm && prev.bpm > 0 && next.bpm > 0
      ? Math.round((next.bpm - prev.bpm) * 10) / 10
      : null;
  return {
    bpmDiff,
    keyCompat: getKeyCompatibility(prev?.key, next.key),
  };
}

export function buildTrackSearchParams(query: string, filters: FilterState) {
  const params: any = { title: query, limit: 50 };

  // Basic Filters Mapping
  if (filters.bpm && filters.bpm > 0) {
    params["bpm"] = filters.bpm.toString();
    params["bpm_range"] = filters.bpmRange.toString();
  }
  if (filters.key) params["key"] = filters.key;
  if (filters.artist) params["artist"] = filters.artist;
  if (filters.genres && filters.genres.length > 0) {
    params["genres"] = filters.genres;
  }

  // Advanced Filters
  if (filters.minEnergy > 0)
    params["min_energy"] = filters.minEnergy.toString();
  if (filters.maxEnergy < 1)
    params["max_energy"] = filters.maxEnergy.toString();
  if (filters.minDanceability > 0)
    params["min_danceability"] = filters.minDanceability.toString();
  if (filters.maxDanceability < 1)
    params["max_danceability"] = filters.maxDanceability.toString();
  if (filters.minBrightness > 0)
    params["min_brightness"] = filters.minBrightness.toString();
  if (filters.maxBrightness < 1)
    params["max_brightness"] = filters.maxBrightness.toString();

  // Vibe Search
  if (filters.vibePrompt) {
    params["vibe_prompt"] = filters.vibePrompt;
  }

  return params;
}
