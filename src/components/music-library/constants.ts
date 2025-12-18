import { FilterState } from "./types";

export const INITIAL_FILTERS: FilterState = {
  bpm: null,
  bpmRange: 5,
  minDuration: null,
  maxDuration: null,
  artist: "",
  album: "",
  genres: [],
  key: "",
  minEnergy: 0.0,
  maxEnergy: 1.0,
  minDanceability: 0.0,
  maxDanceability: 1.0,
  minBrightness: 0.0,
  maxBrightness: 1.0,
  vibePrompt: null,
};

// Camelot Wheel 対応表
export const KEY_OPTIONS = [
  // スケール単位でのフィルタリング用オプション
  { label: "--- All Major Keys (明るい) ---", value: "Major" },
  { label: "--- All Minor Keys (暗い/哀愁) ---", value: "Minor" },

  // 個別キー
  { label: "8B - C Major", value: "C Major" },
  { label: "5A - C Minor", value: "C Minor" },
  { label: "3B - C# Major", value: "C# Major" },
  { label: "12A - C# Minor", value: "C# Minor" },
  { label: "10B - D Major", value: "D Major" },
  { label: "7A - D Minor", value: "D Minor" },
  { label: "5B - D# Major", value: "D# Major" },
  { label: "2A - D# Minor", value: "D# Minor" },
  { label: "12B - E Major", value: "E Major" },
  { label: "9A - E Minor", value: "E Minor" },
  { label: "7B - F Major", value: "F Major" },
  { label: "4A - F Minor", value: "F Minor" },
  { label: "2B - F# Major", value: "F# Major" },
  { label: "11A - F# Minor", value: "F# Minor" },
  { label: "9B - G Major", value: "G Major" },
  { label: "6A - G Minor", value: "G Minor" },
  { label: "4B - G# Major", value: "G# Major" },
  { label: "1A - G# Minor", value: "G# Minor" },
  { label: "11B - A Major", value: "A Major" },
  { label: "8A - A Minor", value: "A Minor" },
  { label: "6B - A# Major", value: "A# Major" },
  { label: "3A - A# Minor", value: "A# Minor" },
  { label: "1B - B Major", value: "B Major" },
  { label: "10A - B Minor", value: "B Minor" },
];

export const LIMIT = 100;
