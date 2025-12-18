import { FilterState } from "@/components/music-library/types";

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
