export interface PerformanceCuePoint {
  slot: number;
  position_ms: number;
  label: string;
  color: string | null;
}

export interface PerformanceLoop {
  id: string;
  start_ms: number;
  end_ms: number;
  label: string;
}

export interface PerformanceBeatGrid {
  bpm: number;
  first_beat_ms: number;
  beats_per_bar: number;
}

export interface PerformanceMetadata {
  track_id: number;
  revision: number;
  cue_points: PerformanceCuePoint[];
  loops: PerformanceLoop[];
  beat_grid: PerformanceBeatGrid | null;
  created_at: string | null;
  updated_at: string | null;
}

export type PerformanceMetadataWrite = Pick<
  PerformanceMetadata,
  "revision" | "cue_points" | "loops" | "beat_grid"
>;
