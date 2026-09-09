# djaly-gemini-genre

Djaly の「ジャンル / サブジャンル未解析」トラックを、Gemini の Gem
(<https://gemini.google.com/gem/0d9581d5a139>) にログイン済みブラウザで投げて判定させ、
結果を **バッチごとに JSON へ都度保存** するツール。

**デプロイ対象外。** リポジトリ直下の `tools/` にあり、Vite / Tauri / Docker の
いずれのビルドにも含まれない（`tsconfig` の `include` は `src` のみ、`.dockerignore`
に `tools` を追加済み）。独自の `package.json` を持ち、ルートの依存とは分離。

---

## 仕組み

1. Djaly バックエンド (`http://localhost:8001`) から未解析トラックを取得
   - `GET /api/genres/unknown-ids` … 対象 ID 全件
   - `GET /api/genres/unknown` … メタデータ + Essentia 特徴量
2. `--batch` 件ずつに分割
3. 永続プロファイル (`.auth/`) の Chrome で Gem を開く（Google ログインは 1 回だけ手動）
4. バッチごとに新しいチャットを開始 → 1 行の JSON を貼って送信 → 応答を待つ
5. 応答から JSON を抽出し `out/<mode>/batch-NNN.json` に保存、
   併せて `out/<mode>/results.json`（全バッチ統合・id 重複は後勝ち）を更新
6. 失敗したバッチは `out/<mode>/batch-NNN.error.txt` に生応答を残して次へ。
   同じコマンドを再実行すると成功済みバッチはスキップして失敗分だけ retry

Gem 側のカスタム指示とサブジャンル語彙は `docs/gemini-gem/` を参照。

## セットアップ

```sh
cd tools/gemini-genre
npm install
npx playwright install chromium   # Google Chrome 未インストールなら
```

## 使い方

Djaly バックエンドを起動しておく（`pnpm backend:dev` など、ポート 8001）。

```sh
# 1) 初回だけ: ブラウザが開くので Google にログイン
npm run login

# 2) 判定 → JSON 保存（DB は変更しない）
npm run classify -- --mode genre --batch 200

# 3) 保存済み results.json を Djaly に反映（DB 更新）
npm run apply -- --mode genre
#   または判定と同時に反映:
npm run classify -- --mode genre --batch 200 --apply
```

## オプション（フラグ / 環境変数）

| フラグ | 環境変数 | 既定 | 説明 |
| --- | --- | --- | --- |
| `--api <url>` | `DJALY_API` | `http://localhost:8001` | Djaly バックエンド |
| `--gem <url>` | `GEMINI_GEM_URL` | 上記 Gem | 対象 Gem |
| `--mode <m>` | `GEMINI_GENRE_MODE` | `genre` | `genre` / `subgenre` / `both` |
| `--batch <n>` | `GEMINI_GENRE_BATCH` | `200` | 1 リクエストの曲数。応答が途中で切れるなら下げる |
| `--limit <n>` | `GEMINI_GENRE_LIMIT` | `0` | 処理する最大曲数（0 = 全部）。試運転に便利 |
| `--out <dir>` | `GEMINI_GENRE_OUT` | `./out` | 出力先 |
| `--profile <dir>` | `GEMINI_GENRE_PROFILE` | `./.auth` | Chrome プロファイル（ログイン保持） |
| `--headless` | `GEMINI_GENRE_HEADLESS=1` | off | ヘッドレス（ログイン済みなら可） |
| `--chromium` | `GEMINI_GENRE_CHROMIUM=1` | off | Chrome ではなく同梱 Chromium を使う |
| `--timeout <ms>` | `GEMINI_GENRE_TIMEOUT` | `240000` | 1 バッチの応答待ち上限 |
| `--apply` | | off | 各バッチ保存後に Djaly へ反映 |
| `--overwrite` | | off | `--apply` 時、検証済みジャンルも上書き |
| `--login-only` | | | ログインだけしてプロファイル保存して終了 |
| `--apply-only` | | | ブラウザを使わず `out/<mode>/results.json` を反映するだけ |

## 出力

```
out/
  genre/
    batch-000.json      { batch, mode, ts, requestedIds, missingIds, count, results[] }
    batch-001.json
    batch-002.error.txt  失敗バッチの生応答
    results.json         全 results を統合した配列（apply-only はこれを読む）
```

`results[]` の各行: `{ id, track, genre, subgenre, confidence, reason }`。

## 注意

- DuckDB は単一ライターなので、DB 反映（`--apply` / `--apply-only`）は
  **動作中の Djaly バックエンド経由**（`POST /api/genres/apply-analyses`）で行う。
  バックエンドを止めて別プロセスから直接 DB を開かないこと。
- Gemini の DOM 変更でセレクタが合わなくなったら `src/gemini.ts` 冒頭の定数を調整。
- 大量に回すと Gemini 側のレート制限に当たることがある。`--limit` で刻むか時間を空ける。
