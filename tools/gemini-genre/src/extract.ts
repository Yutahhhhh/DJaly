import type { GenreResult } from "./plumdeck.ts";

/**
 * Pull the results array out of whatever the Gem replied with.
 * The Gem is told to return raw JSON, but tolerate ```json fences, prose
 * wrappers, and a bare array instead of { results: [...] }.
 */
export function extractResults(reply: string): GenreResult[] {
  const spans = [...fencedBlocks(reply), ...braceSpans(reply), reply.trim()];
  const candidates = [...spans, ...spans.map(repairInnerQuotes)];

  for (const raw of candidates) {
    const parsed = tryParse(raw);
    if (!parsed) continue;
    const rows = Array.isArray(parsed)
      ? parsed
      : Array.isArray((parsed as any).results)
        ? (parsed as any).results
        : null;
    if (rows && rows.every((r: any) => r && typeof r === "object")) {
      const mapped = rows
        .filter((r: any) => r.id !== undefined && r.id !== null)
        .map((r: any) => ({
          id: Number(r.id),
          track: str(r.track),
          genre: str(r.genre),
          subgenre: str(r.subgenre),
          confidence: str(r.confidence),
          reason: str(r.reason),
        }));
      if (mapped.length) return mapped;
    }
  }

  // Last resort: the Gem's records have a fixed key order, so pull them field by
  // field. This survives unescaped quotes inside values (e.g. `"La Voz"`), which
  // defeat a generic JSON parse.
  const bySchema = parseBySchema(reply);
  if (bySchema.length) return bySchema;

  throw new Error("no parseable results array in reply");
}

function parseBySchema(text: string): GenreResult[] {
  const re =
    /"id"\s*:\s*"?(\d+)"?\s*,\s*"track"\s*:\s*"([\s\S]*?)"\s*,\s*"genre"\s*:\s*"([\s\S]*?)"\s*,\s*"subgenre"\s*:\s*"([\s\S]*?)"\s*,\s*"confidence"\s*:\s*"([\s\S]*?)"\s*,\s*"reason"\s*:\s*"([\s\S]*?)"\s*\}/g;
  const out: GenreResult[] = [];
  let m: RegExpExecArray | null;
  while ((m = re.exec(text))) {
    out.push({
      id: Number(m[1]),
      track: str(m[2]),
      genre: str(m[3]),
      subgenre: str(m[4]),
      confidence: str(m[5]),
      reason: str(m[6]),
    });
  }
  return out;
}

function str(v: unknown): string | undefined {
  return typeof v === "string" && v.trim() ? v.trim() : undefined;
}

function tryParse(raw: string): unknown {
  try {
    return JSON.parse(raw);
  } catch {
    return null;
  }
}

/**
 * Escape `"` that appear *inside* a JSON string value. A quote is treated as a
 * real string terminator only when the next non-space char is one of : , } ] —
 * otherwise it is a stray inner quote and gets backslash-escaped.
 */
function repairInnerQuotes(text: string): string {
  let out = "";
  let inStr = false;
  let esc = false;
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (!inStr) {
      out += c;
      if (c === '"') inStr = true;
      continue;
    }
    if (esc) {
      out += c;
      esc = false;
      continue;
    }
    if (c === "\\") {
      out += c;
      esc = true;
      continue;
    }
    if (c === '"') {
      const next = text.slice(i + 1).match(/^\s*(.)/)?.[1] ?? "";
      if (next === "" || ":,}]".includes(next)) {
        out += c;
        inStr = false;
      } else {
        out += '\\"';
      }
      continue;
    }
    out += c;
  }
  return out;
}

function* fencedBlocks(text: string): Generator<string> {
  const re = /```(?:json|JSON)?\s*([\s\S]*?)```/g;
  let m: RegExpExecArray | null;
  while ((m = re.exec(text))) yield m[1].trim();
}

/** Every balanced {...} or [...] span, longest first. */
function braceSpans(text: string): string[] {
  const spans: string[] = [];
  for (const [open, close] of [
    ["{", "}"],
    ["[", "]"],
  ] as const) {
    let depth = 0;
    let start = -1;
    let inStr = false;
    let esc = false;
    for (let i = 0; i < text.length; i++) {
      const c = text[i];
      if (inStr) {
        if (esc) esc = false;
        else if (c === "\\") esc = true;
        else if (c === '"') inStr = false;
        continue;
      }
      if (c === '"') inStr = true;
      else if (c === open) {
        if (depth === 0) start = i;
        depth++;
      } else if (c === close && depth > 0) {
        depth--;
        if (depth === 0 && start >= 0) spans.push(text.slice(start, i + 1));
      }
    }
  }
  return spans.sort((a, b) => b.length - a.length);
}
