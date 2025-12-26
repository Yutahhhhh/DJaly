import { create } from "zustand";
import { Track } from "@/types";

interface PlayerState {
  currentTrack: Track | null;
  isPlaying: boolean;
  volume: number;
  progress: number;
  duration: number;
  seekRequest: number | null;

  setTrack: (track: Track | null) => void;
  setIsPlaying: (isPlaying: boolean) => void;
  setVolume: (volume: number) => void;
  setProgress: (progress: number) => void;
  setDuration: (duration: number) => void;
  play: (track?: Track) => void;
  playAt: (track: Track, seconds: number) => void;
  pause: () => void;
  togglePlay: () => void;
  clearSeekRequest: () => void;
}

export const usePlayerStore = create<PlayerState>((set, get) => ({
  currentTrack: null,
  isPlaying: false,
  volume: 0.8,
  progress: 0,
  duration: 0,
  seekRequest: null,

  setTrack: (track) => set({ currentTrack: track }),
  setIsPlaying: (isPlaying) => set({ isPlaying }),
  setVolume: (volume) => set({ volume }),
  setProgress: (progress) => set({ progress }),
  setDuration: (duration) => set({ duration }),

  play: (track) => {
    if (track) {
      set({ currentTrack: track, isPlaying: true });
    } else {
      set({ isPlaying: true });
    }
  },

  playAt: (track, seconds) => {
    // 3秒前から再生（0秒以下にならないように調整）
    const startTime = Math.max(0, seconds - 3);
    set({
      currentTrack: track,
      isPlaying: true,
      seekRequest: startTime,
    });
  },

  pause: () => set({ isPlaying: false }),

  togglePlay: () => {
    const { isPlaying, currentTrack } = get();
    if (currentTrack) {
      set({ isPlaying: !isPlaying });
    }
  },

  clearSeekRequest: () => set({ seekRequest: null }),
}));
