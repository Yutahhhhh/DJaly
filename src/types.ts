export interface Track {
  id: number;
  filepath: string;
  title: string;
  artist: string;
  album: string;
  bpm: number;
  key: string;
  genre: string;
  subgenre?: string;
  year?: number;
  duration: number;
  // New Analysis Features
  energy: number; // 0.0 - 1.0
  danceability: number; // 0.0 - 1.0
  brightness: number; // 0.0 - 1.0
  contrast: number; // 0.0 - 1.0
  noisiness: number; // 0.0 - 1.0
  loudness: number; // dB (negative)
  is_genre_verified?: boolean;
  has_lyrics?: boolean;
}
