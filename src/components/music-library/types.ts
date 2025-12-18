export interface FilterState {
  bpm: number | null;
  bpmRange: number;
  minDuration: number | null;
  maxDuration: number | null;
  artist: string;
  album: string;
  genres: string[]; // Changed from genre: string
  key: string; // Added: "C Major", etc.
  // Advanced Features (0.0 - 1.0)
  minEnergy: number;
  maxEnergy: number;
  minDanceability: number;
  maxDanceability: number;
  minBrightness: number;
  maxBrightness: number;
  vibePrompt: string | null;
}
