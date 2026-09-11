export type AnalysisProfile = "auto" | "light" | "full";

export const ANALYSIS_PROFILE_STORAGE_KEY = "plumdeck.analysisProfile";

export function normalizeAnalysisProfile(value: unknown): AnalysisProfile {
  return value === "light" || value === "full" ? value : "auto";
}

export function currentAnalysisProfile(): AnalysisProfile {
  if (typeof localStorage === "undefined") return "auto";
  return normalizeAnalysisProfile(localStorage.getItem(ANALYSIS_PROFILE_STORAGE_KEY));
}

export function rememberAnalysisProfile(value: unknown): AnalysisProfile {
  const profile = normalizeAnalysisProfile(value);
  if (typeof localStorage !== "undefined") {
    localStorage.setItem(ANALYSIS_PROFILE_STORAGE_KEY, profile);
  }
  return profile;
}
