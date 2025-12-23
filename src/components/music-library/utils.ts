import { FilterState } from "./types";

export function buildTrackSearchParams(
  title: string,
  filters: FilterState,
  limit: number = 50,
  offset: number = 0
): Record<string, any> {
  const params: Record<string, any> = {
    status: "all",
    limit: limit.toString(),
    offset: offset.toString(),
  };

  if (title) params["title"] = title;

  // Basic Filters
  if (filters.bpm && filters.bpm > 0) {
    params["bpm"] = filters.bpm.toString();
    params["bpm_range"] = filters.bpmRange.toString();
  }
  if (filters.key) params["key"] = filters.key;
  if (filters.artist) params["artist"] = filters.artist;
  if (filters.album) params["album"] = filters.album;
  if (filters.genres && filters.genres.length > 0) {
    // API client handles array serialization usually, but let's check how it was done.
    // In the original code: params["genres"] = currentFilters.genres;
    // If the API client expects an array, we should keep it as any or handle it.
    // The original code used Record<string, any>.
    // Let's change return type to Record<string, any> to be safe.
    params["genres"] = filters.genres as any;
  }
  if (filters.minDuration)
    params["min_duration"] = filters.minDuration.toString();
  if (filters.maxDuration)
    params["max_duration"] = filters.maxDuration.toString();

  // Advanced Feature Filters
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

  if (filters.minYear) params["min_year"] = filters.minYear.toString();
  if (filters.maxYear) params["max_year"] = filters.maxYear.toString();

  // Vibe Search
  if (filters.vibePrompt) {
    params["vibe_prompt"] = filters.vibePrompt;
  }

  return params;
}
