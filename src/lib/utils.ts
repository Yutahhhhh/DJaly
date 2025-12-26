import { clsx, type ClassValue } from "clsx"
import { twMerge } from "tailwind-merge"
import { formatDistanceToNow } from "date-fns"

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

export function formatDuration(sec: number) {
  if (!sec || isNaN(sec)) return "-:--";
  const m = Math.floor(sec / 60);
  const s = Math.floor(sec % 60);
  return `${m}:${s.toString().padStart(2, "0")}`;
}

export function formatRelativeTime(date: Date | string | number) {
  return formatDistanceToNow(new Date(date), { addSuffix: true });
}

export function formatTime(time: number) {
  const minutes = Math.floor(time / 60);
  const seconds = Math.floor(time % 60);
  return `${minutes}:${seconds.toString().padStart(2, "0")}`;
};

/**
 * Normalize lyrics time tags to standard LRC format [MM:SS.xxx]
 * Converts various formats like [MM:SS.xx.x] to [MM:SS.xxx]
 */
export function normalizeLyricsTimeTags(text: string) {
  if (!text) return text;
  
  // Convert [MM:SS.xx.x] to [MM:SS.xxx]
  return text.replace(
    /\[(\d{2}):(\d{2})\.(\d{2})\.(\d+)\]/g,
    (_, min, sec, ms, extra) => {
      // Combine ms and extra digit as milliseconds (pad to 3 digits)
      const totalMs = (ms + extra).padEnd(3, '0').substring(0, 3);
      return `[${min}:${sec}.${totalMs}]`;
    }
  );
}

/**
 * Check if text contains LRC time tags
 */
export function hasLyricsTimeTags(text: string) {
  return /\[\d{2}:\d{2}\.\d{2,3}(\.\d+)?\]/.test(text);
}

// Audio playback constants
export const AUDIO_CONSTANTS = {
  // Retry delays (ms) for seeking to prevent browser reset
  SEEK_RETRY_DELAYS: [50, 150, 300] as const,
  // Maximum time difference (seconds) before re-seeking
  SEEK_TOLERANCE: 1.5,
  // Threshold (seconds) to detect invalid zero-reset
  ZERO_RESET_THRESHOLD: 0.5,
  // Minimum audio ready state for seeking (HAVE_CURRENT_DATA)
  MIN_READY_STATE_FOR_SEEK: 2,
} as const;

/**
 * Safely play audio element with error handling
 */
export async function safePlayAudio(
  audio: HTMLAudioElement,
  onError?: () => void
): Promise<boolean> {
  try {
    await audio.play();
    return true;
  } catch (error) {
    console.warn("Failed to play audio:", error);
    onError?.();
    return false;
  }
}

/**
 * Check if audio is ready for seeking
 */
export function isAudioReadyForSeek(audio: HTMLAudioElement): boolean {
  return audio.readyState >= AUDIO_CONSTANTS.MIN_READY_STATE_FOR_SEEK;
}

/**
 * Check if current time significantly differs from target
 */
export function isTimeOffTarget(
  currentTime: number,
  targetTime: number,
  tolerance: number = AUDIO_CONSTANTS.SEEK_TOLERANCE
): boolean {
  return Math.abs(currentTime - targetTime) > tolerance;
}

/**
 * Check if time indicates an invalid zero-reset
 */
export function isInvalidZeroReset(
  currentTime: number,
  threshold: number = AUDIO_CONSTANTS.ZERO_RESET_THRESHOLD
): boolean {
  return currentTime < threshold;
}