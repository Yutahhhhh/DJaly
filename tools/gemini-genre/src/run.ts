import fs from "node:fs";
import path from "node:path";
import { loadConfig, describe, type Config } from "./config.ts";
import {
  fetchUnknownTracks,
  chunk,
  applyResults,
  type GenreResult,
  type TrackInput,
} from "./djaly.ts";
import { extractResults } from "./extract.ts";
import { GeminiGem } from "./gemini.ts";

function preamble(cfg: Config): string {
  const focus =
    cfg.mode === "genre"
      ? "Classify the main genre (subgenre optional)."
      : cfg.mode === "subgenre"
        ? "Classify the subgenre."
        : "Classify the main genre and one subgenre.";
  return (
    `${focus} ` +
    `Reply with ONLY a compact JSON object {"results":[{"id","track","genre","subgenre","confidence","reason"}, ...]} ` +
    `— no markdown, no code fence, no commentary. Input:`
  );
}

const batchFile = (dir: string, i: number) =>
  path.join(dir, `batch-${String(i).padStart(3, "0")}.json`);
const errorFile = (dir: string, i: number) =>
  path.join(dir, `batch-${String(i).padStart(3, "0")}.error.txt`);

function mergeBatches(dir: string): GenreResult[] {
  const byId = new Map<number, GenreResult>();
  for (const name of fs.readdirSync(dir).sort()) {
    if (!/^batch-\d+\.json$/.test(name)) continue;
    const doc = JSON.parse(fs.readFileSync(path.join(dir, name), "utf8"));
    for (const r of doc.results as GenreResult[]) byId.set(r.id, r);
  }
  return [...byId.values()];
}

async function applyOnly(cfg: Config, dir: string) {
  const file = path.join(dir, "results.json");
  if (!fs.existsSync(file)) throw new Error(`not found: ${file}`);
  const results = JSON.parse(fs.readFileSync(file, "utf8")) as GenreResult[];
  console.log(`applying ${results.length} results from ${file} …`);
  const { applied, skipped } = await applyResults(cfg, results);
  console.log(`done: applied ${applied}, skipped ${skipped}`);
}

const HELP = `djaly-gemini-genre — classify Djaly's unanalyzed genres via a Gemini Gem

  npm run login                 open the browser once, log into Google
  npm run classify              -> out/<mode>/batch-NNN.json (+ results.json)
  npm run classify -- --apply   also POST each batch back to Djaly
  npm run apply                 POST an existing out/<mode>/results.json only

flags: --mode genre|subgenre|both  --batch N  --limit N  --api URL  --gem URL
       --out DIR  --profile DIR  --headless  --chromium  --timeout MS
       --apply  --overwrite  --login-only  --apply-only
see README.md for the full table.`;

async function main() {
  if (process.argv.slice(2).some((a) => a === "--help" || a === "-h")) {
    console.log(HELP);
    return;
  }
  const cfg = loadConfig(process.argv);
  console.log("djaly-gemini-genre\n" + describe(cfg) + "\n");

  const dir = path.join(cfg.outDir, cfg.mode);
  fs.mkdirSync(dir, { recursive: true });

  if (cfg.applyOnly) {
    await applyOnly(cfg, dir);
    return;
  }

  if (cfg.loginOnly) {
    const gem = new GeminiGem(cfg);
    await gem.open();
    console.log("ログインOK。プロファイルを保存しました:", cfg.userDataDir);
    await gem.close();
    return;
  }

  const tracks: TrackInput[] = await fetchUnknownTracks(cfg);
  console.log(`unanalyzed (${cfg.mode}): ${tracks.length} tracks`);
  if (tracks.length === 0) return;

  const batches = chunk(tracks, cfg.batchSize);
  console.log(`-> ${batches.length} batch(es) of up to ${cfg.batchSize}\n`);

  const gem = new GeminiGem(cfg);
  await gem.open();

  const failed: number[] = [];
  let okBatches = 0;
  let appliedTotal = 0;

  for (let i = 0; i < batches.length; i++) {
    const out = batchFile(dir, i);
    if (fs.existsSync(out)) {
      console.log(`batch ${i + 1}/${batches.length}: cached, skip`);
      okBatches++;
      continue;
    }

    const batch = batches[i];
    const ids = batch.map((t) => t.id);
    console.log(
      `batch ${i + 1}/${batches.length}: ${batch.length} tracks (id ${ids[0]}…${ids.at(-1)})`,
    );

    let reply = "";
    try {
      await gem.newChat();
      reply = await gem.ask(
        `${preamble(cfg)} ${JSON.stringify({ tracks: batch })}`,
        cfg.responseTimeoutMs,
      );
      const results = extractResults(reply);
      const got = new Set(results.map((r) => r.id));
      const missing = ids.filter((id) => !got.has(id));

      fs.writeFileSync(
        out,
        JSON.stringify(
          {
            batch: i,
            mode: cfg.mode,
            ts: new Date().toISOString(),
            requestedIds: ids,
            missingIds: missing,
            count: results.length,
            results,
          },
          null,
          2,
        ),
      );
      console.log(
        `  saved ${results.length}/${batch.length} -> ${path.relative(process.cwd(), out)}` +
          (missing.length ? `  (missing ${missing.length})` : ""),
      );
      okBatches++;

      if (cfg.apply) {
        const { applied } = await applyResults(cfg, results);
        appliedTotal += applied;
        console.log(`  applied ${applied} to Djaly`);
      }
    } catch (err) {
      failed.push(i);
      fs.writeFileSync(
        errorFile(dir, i),
        `# batch ${i} failed: ${(err as Error).message}\n` +
          `# requestedIds: ${JSON.stringify(ids)}\n\n${reply}`,
      );
      console.log(
        `  FAILED: ${(err as Error).message} -> ${path.relative(process.cwd(), errorFile(dir, i))}`,
      );
    }

    const merged = mergeBatches(dir);
    fs.writeFileSync(
      path.join(dir, "results.json"),
      JSON.stringify(merged, null, 2),
    );
  }

  await gem.close();

  fs.writeFileSync(
    path.join(dir, "results.json"),
    JSON.stringify(mergeBatches(dir), null, 2),
  );

  console.log(
    `\ndone: ${okBatches}/${batches.length} batches ok` +
      (failed.length ? `, failed [${failed.map((n) => n + 1).join(", ")}]` : "") +
      (cfg.apply ? `, applied ${appliedTotal} to Djaly` : "") +
      `\nmerged -> ${path.relative(process.cwd(), path.join(dir, "results.json"))}`,
  );
  if (failed.length) {
    console.log(
      "re-run the same command to retry only the failed batches (cached ones are skipped).",
    );
    process.exitCode = 1;
  }
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
