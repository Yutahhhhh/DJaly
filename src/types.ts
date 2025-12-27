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
  energy: number;
  danceability: number;
  brightness: number;
  contrast: number;
  noisiness: number;
  loudness: number;
  is_genre_verified?: boolean;
  has_lyrics?: boolean;
}
