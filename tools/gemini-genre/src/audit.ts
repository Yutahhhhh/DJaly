/**
 * Audit already-classified tracks: hand Gemini each track's CURRENT genre +
 * features and ask whether it's right. Input is a local JSON array
 * (id, artist, title, current_genre, current_subgenre, bpm, energy, ...).
 *
 *   npx tsx src/audit.ts <candidates.json> [--batch 150] [--out ./out/audit]
 *
 * Output: out/audit/batch-NNN.json + results.json with rows
 *   { id, verdict: "keep"|"change", genre, subgenre, confidence, reason }
 */
import fs from "node:fs";
import path from "node:path";
import { loadConfig } from "./config.ts";
import { GeminiGem } from "./gemini.ts";
import { extractResults } from "./extract.ts";

interface Cand {
  id: number;
  artist: string;
  title: string;
  current_genre: string;
  current_subgenre?: string;
  bpm?: number;
  energy?: number;
  danceability?: number;
  brightness?: number;
  noisiness?: number;
}

const GENRES = [
  "African","Afrobeats","Bass","Country","Dance","Downtempo","Electronic","Funk",
  "Hip Hop","House","Jazz","Latin","Other","Pop","R&B","Reggae","Rock","Techno","Trance","Trap",
];

const PREAMBLE =
  `You are auditing genre tags in a DJ music library. For each track you get its CURRENT ` +
  `"genre / subgenre" plus Essentia features (energy/danceability/brightness/noisiness, 0-1). ` +
  `Decide if the CURRENT MAIN genre is an acceptable fit. Main-genre vocabulary: ${GENRES.join(", ")}. ` +
  `Reply with ONLY a compact JSON object ` +
  `{"results":[{"id","verdict","genre","subgenre","confidence","reason"}, ...]} — no markdown, no prose. ` +
  `verdict is "keep" or "change". For "keep" echo the current genre+subgenre. For "change" give the ` +
  `corrected main genre (from the vocabulary) and a fitting subgenre. Prefer "keep" unless the current ` +
  `main genre is clearly wrong (e.g. a reggaeton track tagged Pop, a drum & bass track tagged Hip Hop, ` +
  `a house track tagged Electronic). Keep reason under 15 words. Input:`;

const compact = (c: Cand) => ({
  id: c.id,
  track: `${c.artist} - ${c.title}`.replace(/[\r\n"\\]+/g, " ").trim(),
  current: `${c.current_genre} / ${c.current_subgenre || ""}`.trim(),
  bpm: c.bpm,
  energy: c.energy,
  danceability: c.danceability,
  brightness: c.brightness,
  noisiness: c.noisiness,
});

function chunk<T>(a: T[], n: number): T[][] {
  const o: T[][] = [];
  for (let i = 0; i < a.length; i += n) o.push(a.slice(i, i + n));
  return o;
}

async function main() {
  const cfg = loadConfig(process.argv);
  const file = process.argv.slice(2).find((a) => !a.startsWith("--"));
  if (!file) throw new Error("usage: tsx src/audit.ts <candidates.json> [--batch N]");
  const cands: Cand[] = JSON.parse(fs.readFileSync(file, "utf8"));
  const dir = path.join(cfg.outDir, "audit");
  fs.mkdirSync(dir, { recursive: true });

  const batches = chunk(cands, cfg.batchSize);
  console.log(`audit: ${cands.length} tracks -> ${batches.length} batch(es) of ${cfg.batchSize}`);

  const gem = new GeminiGem(cfg);
  await gem.open();

  const failed: number[] = [];
  for (let i = 0; i < batches.length; i++) {
    const out = path.join(dir, `batch-${String(i).padStart(3, "0")}.json`);
    if (fs.existsSync(out)) {
      console.log(`batch ${i + 1}/${batches.length}: cached`);
      continue;
    }
    const b = batches[i];
    const ids = b.map((c) => c.id);
    console.log(`batch ${i + 1}/${batches.length}: ${b.length} tracks`);
    let reply = "";
    try {
      await gem.newChat();
      reply = await gem.ask(
        `${PREAMBLE} ${JSON.stringify({ tracks: b.map(compact) })}`,
        cfg.responseTimeoutMs,
      );
      const rows = extractResults(reply).map((r: any) => ({
        id: r.id,
        verdict: (r.verdict || "").toLowerCase() === "change" ? "change" : "keep",
        genre: r.genre,
        subgenre: r.subgenre,
        confidence: r.confidence,
        reason: r.reason,
      }));
      const got = new Set(rows.map((r) => r.id));
      fs.writeFileSync(
        out,
        JSON.stringify(
          { batch: i, ts: new Date().toISOString(), requestedIds: ids, missingIds: ids.filter((x) => !got.has(x)), count: rows.length, results: rows },
          null,
          2,
        ),
      );
      const ch = rows.filter((r) => r.verdict === "change").length;
      console.log(`  ${rows.length}/${b.length} (${ch} change)`);
    } catch (err) {
      failed.push(i);
      fs.writeFileSync(path.join(dir, `batch-${String(i).padStart(3, "0")}.error.txt`), `${(err as Error).message}\n\n${reply}`);
      console.log(`  FAILED: ${(err as Error).message}`);
    }
    // rebuild merged
    const merged: any[] = [];
    for (const n of fs.readdirSync(dir).sort()) {
      if (/^batch-\d+\.json$/.test(n)) merged.push(...JSON.parse(fs.readFileSync(path.join(dir, n), "utf8")).results);
    }
    fs.writeFileSync(path.join(dir, "results.json"), JSON.stringify(merged, null, 2));
  }
  await gem.close();
  console.log(`done. failed batches: ${failed.length ? failed.map((n) => n + 1).join(",") : "none"}`);
  if (failed.length) process.exitCode = 1;
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
