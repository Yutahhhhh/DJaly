import fs from "node:fs";
import type { Config, Mode } from "./config.ts";

/** Subset of plumdeck's TrackRead we send to Gemini. */
export interface TrackInput {
  id: number;
  artist: string;
  title: string;
  year?: number | null;
  bpm?: number;
  key?: string;
  energy?: number;
  danceability?: number;
  brightness?: number;
  noisiness?: number;
}

/** One row of the Gem's JSON reply. */
export interface GenreResult {
  id: number;
  track?: string;
  genre?: string;
  subgenre?: string;
  confidence?: string;
  reason?: string;
}

const round = (n: unknown): number | undefined =>
  typeof n === "number" && Number.isFinite(n)
    ? Math.round(n * 1000) / 1000
    : undefined;

/**
 * Neutralise characters that make the model emit invalid JSON when it echoes
 * the value back (unescaped `"` in a title is the big one), and control chars.
 */
const clean = (s: unknown): string =>
  String(s ?? "")
    .replace(/[\u0000-\u001f\u007f]/g, " ")
    .replace(/["\\]/g, "'")
    .replace(/\s+/g, " ")
    .trim();

async function getJson<T>(url: string): Promise<T> {
  const res = await fetch(url);
  if (!res.ok) {
    throw new Error(`GET ${url} -> ${res.status} ${res.statusText}`);
  }
  return (await res.json()) as T;
}

/**
 * Pull every unanalyzed track for the given mode from the running plumdeck backend.
 * Uses /api/genres/unknown-ids for the full id set, then pages /api/genres/unknown
 * for the metadata + Essentia features.
 */
export async function fetchUnknownTracks(
  cfg: Config,
  mode: Mode = cfg.mode,
): Promise<TrackInput[]> {
  let ids = await getJson<number[]>(
    `${cfg.plumdeckApi}/api/genres/unknown-ids?mode=${mode}`,
  );
  if (cfg.idsFile) {
    const only = new Set<number>(
      JSON.parse(fs.readFileSync(cfg.idsFile, "utf8")).map(Number),
    );
    ids = ids.filter((id) => only.has(id));
    console.log(`ids-file: restricting to ${ids.length} of ${only.size} listed`);
  }
  const wanted = cfg.limit > 0 ? ids.slice(0, cfg.limit) : ids;
  const targetCount = wanted.length;
  const wantedSet = new Set(wanted);

  const page = 200;
  const rows: TrackInput[] = [];
  for (let offset = 0; rows.length < targetCount; offset += page) {
    const chunk = await getJson<any[]>(
      `${cfg.plumdeckApi}/api/genres/unknown?mode=${mode}&offset=${offset}&limit=${page}`,
    );
    if (chunk.length === 0) break;
    for (const t of chunk) {
      if (!wantedSet.has(t.id)) continue;
      rows.push({
        id: t.id,
        artist: clean(t.artist),
        title: clean(t.title),
        year: t.year ?? undefined,
        bpm: round(t.bpm),
        key: t.key || undefined,
        energy: round(t.energy),
        danceability: round(t.danceability),
        brightness: round(t.brightness),
        noisiness: round(t.noisiness),
      });
    }
  }
  // /unknown ordering matches /unknown-ids, but clamp defensively.
  return cfg.limit > 0 ? rows.slice(0, cfg.limit) : rows;
}

export function chunk<T>(items: T[], size: number): T[][] {
  const out: T[][] = [];
  for (let i = 0; i < items.length; i += size) out.push(items.slice(i, i + size));
  return out;
}

/** POST classifications back to plumdeck so the DB is updated. */
export async function applyResults(
  cfg: Config,
  results: GenreResult[],
): Promise<{ applied: number; skipped: number }> {
  const analyses = results
    .filter((r) => r && typeof r.id === "number")
    .map((r) => ({
      track_id: r.id,
      genre: r.genre ?? null,
      subgenre: r.subgenre ?? null,
      confidence: r.confidence ?? "Medium",
      reason: r.reason ?? "",
    }));

  if (analyses.length === 0) return { applied: 0, skipped: 0 };

  const res = await fetch(`${cfg.plumdeckApi}/api/genres/apply-analyses`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({
      analyses,
      mode: cfg.mode,
      overwrite: cfg.overwrite,
    }),
  });
  if (!res.ok) {
    throw new Error(
      `POST /api/genres/apply-analyses -> ${res.status} ${res.statusText}: ${await res
        .text()
        .catch(() => "")}`,
    );
  }
  const body = (await res.json()) as { results?: unknown[] };
  const applied = Array.isArray(body.results) ? body.results.length : 0;
  return { applied, skipped: analyses.length - applied };
}
