import { create } from 'zustand';
import { Track } from '@/types';

interface PlayerState {
  currentTrack: Track | null;
  isPlaying: boolean;
  volume: number;
  progress: number;
  duration: number;
  
  // Actions
  setTrack: (track: Track | null) => void;
  setIsPlaying: (isPlaying: boolean) => void;
  setVolume: (volume: number) => void;
  setProgress: (progress: number) => void;
  setDuration: (duration: number) => void;
  play: (track?: Track) => void;
  pause: () => void;
  togglePlay: () => void;
}

export const usePlayerStore = create<PlayerState>((set, get) => ({
  currentTrack: null,
  isPlaying: false,
  volume: 0.8,
  progress: 0,
  duration: 0,

  setTrack: (track) => set({ currentTrack: track }),
  setIsPlaying: (isPlaying) => set({ isPlaying }),
  setVolume: (volume) => set({ volume }),
  setProgress: (progress) => set({ progress }),
  setDuration: (duration) => set({ duration }),
  
  play: (track) => {
    const state = get();
    if (track) {
      if (state.currentTrack?.id === track.id) {
        set({ isPlaying: true });
      } else {
        set({ currentTrack: track, isPlaying: true });
      }
    } else {
      set({ isPlaying: true });
    }
  },
  
  pause: () => set({ isPlaying: false }),
  
  togglePlay: () => {
    const { isPlaying, currentTrack } = get();
    if (currentTrack) {
      set({ isPlaying: !isPlaying });
    }
  },
}));
