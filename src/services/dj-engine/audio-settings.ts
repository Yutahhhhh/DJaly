import type { MicrophoneSettings } from "../../types/dj-engine.ts";

export const DEFAULT_MICROPHONE: MicrophoneSettings = {
  deviceId: null, channel: 0, enabled: false, gain: 1,
  duckingEnabled: false, duckingStrength: 0.65,
};
const STORAGE_KEY = "djaly.microphone";

/** Audio snapshots also carry meters/status; the command accepts settings only. */
export function microphoneCommandParams(settings: Partial<MicrophoneSettings>) {
  const microphone: Partial<MicrophoneSettings> = {};
  for (const key of ["deviceId", "channel", "enabled", "gain", "duckingEnabled", "duckingStrength"] as const) {
    if (settings[key] !== undefined) Object.assign(microphone, { [key]: settings[key] });
  }
  return { microphone };
}

export function parseMicrophoneSettings(raw: string | null): MicrophoneSettings | null {
  if (!raw) return null;
  try {
    const value = JSON.parse(raw) as MicrophoneSettings;
    if (!value || (value.deviceId !== null && typeof value.deviceId !== "string")
      || !Number.isInteger(value.channel) || value.channel < 0 || value.channel > 255
      || typeof value.enabled !== "boolean" || typeof value.duckingEnabled !== "boolean"
      || !Number.isFinite(value.gain) || value.gain < 0 || value.gain > 4
      || !Number.isFinite(value.duckingStrength) || value.duckingStrength < 0 || value.duckingStrength > 1) return null;
    return { deviceId: value.deviceId, channel: value.channel, enabled: value.enabled,
      gain: value.gain, duckingEnabled: value.duckingEnabled, duckingStrength: value.duckingStrength };
  } catch { return null; }
}

export function savedMicrophoneSettings(): MicrophoneSettings | null {
  return parseMicrophoneSettings(localStorage.getItem(STORAGE_KEY));
}

export function saveMicrophoneSettings(settings: MicrophoneSettings) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(microphoneCommandParams(settings).microphone));
}
