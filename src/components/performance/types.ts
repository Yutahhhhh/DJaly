import type { DeckId, TrackDescriptor } from "@/types/dj-engine";

/** Optional seam for loading a track from plumdeck's library instead of the manual form. */
export type PerformanceTrackLoader = (
  deck: DeckId
) => TrackDescriptor | null | Promise<TrackDescriptor | null>;

export interface PerformanceViewProps {
  onRequestTrack?: PerformanceTrackLoader;
}
