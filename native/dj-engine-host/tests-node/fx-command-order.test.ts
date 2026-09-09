import test from "node:test";
import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { globSync } from "node:fs";

/**
 * PAD FX は押している間だけ掛かる momentary 操作なので、オン・オフのどちらも
 * 落としてはいけない。以前 setFx は latest-wins キュー (`continuous`) を通って
 * おり、待機中の値が上書きされて押下の `true` が離した `false` に置き換わり、
 * エフェクトが数ミリ秒しか掛からなかった＝掛かっていないように聞こえていた。
 *
 * client.ts は拡張子なし import を使うので、node 単体では解決できない。
 * リポジトリにある esbuild で束ねてから読み込む。
 */
const repoRoot = path.resolve(import.meta.dirname, "../../..");
const workDir = mkdtempSync(path.join(tmpdir(), "djaly-fx-"));
const bundle = path.join(workDir, "client.mjs");
const esbuildBin = globSync(path.join(repoRoot, "node_modules/.pnpm/esbuild@*/node_modules/esbuild/bin/esbuild"))[0];
assert.ok(esbuildBin, "esbuild binary not found in the pnpm store");
execFileSync(esbuildBin, [
  path.join(repoRoot, "src/services/dj-engine/client.ts"),
  "--bundle", "--format=esm", "--platform=neutral", `--outfile=${bundle}`,
]);
const { DjEngineClient } = await import(bundle);
process.on("exit", () => rmSync(workDir, { recursive: true, force: true }));

function clientWithTransport() {
  const sent: { op: string; params: Record<string, unknown> }[] = [];
  const client = new DjEngineClient();
  client.send = async (op: string, params: Record<string, unknown>) => { sent.push({ op, params }); return {}; };
  return { client, sent };
}

/** UI は `void run(...)` で待たずに投げる。送信を遅くして重なりを再現する。 */
function slowClient() {
  const sent: { op: string; params: Record<string, unknown> }[] = [];
  const client = new DjEngineClient();
  let release!: () => void;
  const gate = new Promise<void>((resolve) => { release = resolve; });
  client.send = async (op: string, params: Record<string, unknown>) => {
    await gate;
    sent.push({ op, params });
    return {};
  };
  return { client, sent, release };
}

test("重なった PAD FX 操作がひとつも落ちない", async () => {
  const { client, sent, release } = slowClient();
  // 押す → 再レンダーで再送 → 離す。待たずに連射するのが実際の呼ばれ方。
  const calls = [
    client.setFx("A", "echo", true, 0.5),
    client.setFx("A", "echo", true, 0.5),
    client.setFx("A", "echo", false, 0.5),
  ];
  release();
  await Promise.all(calls);
  assert.equal(sent.length, 3, `全ての操作が送られること (送信: ${JSON.stringify(sent.map(e => e.params.enabled))})`);
  assert.deepEqual(sent.map((entry: { params: { enabled: boolean } }) => entry.params.enabled), [true, true, false]);
});

test("掛け替えの『前を切る』が後続に上書きされない", async () => {
  const { client, sent, release } = slowClient();
  const calls = [
    client.setFx("A", "echo", true, 0.5),
    client.setFx("A", "echo", false, 0.5),
    client.setFx("A", "reverb", true, 0.5),
  ];
  release();
  await Promise.all(calls);
  assert.deepEqual(
    sent.map((entry: { params: { effect: string; enabled: boolean } }) => [entry.params.effect, entry.params.enabled]),
    [["echo", true], ["echo", false], ["reverb", true]],
  );
});

test("FX の押下と解放はどちらも送られ、順序も保たれる", async () => {
  const { client, sent } = clientWithTransport();
  await client.setFx("A", "echo", true, 0.5);
  await client.setFx("A", "echo", false, 0.5);
  assert.deepEqual(sent.map((entry: { op: string }) => entry.op), ["mixer.fx.set", "mixer.fx.set"]);
  assert.deepEqual(sent.map((entry: { params: { enabled: boolean } }) => entry.params.enabled), [true, false]);
});

test("パッドを移るときの『前を切って次を掛ける』で中間のオフが消えない", async () => {
  const { client, sent } = clientWithTransport();
  await client.setFx("A", "echo", true, 0.5);
  await client.setFx("A", "echo", false, 0.5);
  await client.setFx("A", "reverb", true, 0.5);
  assert.deepEqual(
    sent.map((entry: { params: { effect: string; enabled: boolean } }) => [entry.params.effect, entry.params.enabled]),
    [["echo", true], ["echo", false], ["reverb", true]],
  );
});

test("深さと対象デッキが送信値にそのまま乗る", async () => {
  const { client, sent } = clientWithTransport();
  await client.setFx("B", "phaser", true, 0.32);
  assert.equal(sent[0].params.mix, 0.32);
  assert.equal(sent[0].params.deck, "B");
});

test("拡張したエフェクト名はクライアント側の検証を通る", async () => {
  const { client, sent } = clientWithTransport();
  for (const effect of ["echo", "reverb", "flanger", "phaser", "filter", "bitcrusher", "distortion", "autopan", "tremolo", "moogladder4filter"]) {
    await client.setFx("A", effect, true, 0.5);
  }
  assert.equal(sent.length, 10);
});
