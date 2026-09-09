# 2026-09-09 スクラッチ修正版 v0.4.8 ローカル配備

- `/Applications/Djaly.app` を v0.4.7 から v0.4.8 に更新し、インストール先から起動した。GitHub公開・アップロードは実施していない。
- バックエンドは現在の作業ツリーから PyInstaller spec で再生成。Tauri Performance ビルドに、実曲で検証した Mixxx 音声エンジンを同梱した。
- スクラッチ切り返し・停止応答、逆回転継続、BPM・解析グリッド、PAD・サンプラー・BEAT FX の作業ツリー上の修正を含む。実曲比較の詳細は `scratch-response-real-music-20260909.md` を参照。

## 復元用保存

- 旧アプリ：`/Applications/Djaly-0.4.7-backup-20260909-184513.app`
- DB：`~/Library/Application Support/Djaly/backups/20260909-before-scratch-deploy-184153/`
- アプリ停止中に DuckDB 本体・WAL、解析ジョブSQLite本体・SHM・WALの5ファイルを保存し、全ファイルのSHA256一致を確認した。

## 検証

- バックエンド：337テスト成功。ルートからのpytestは別プロジェクト `rekordbox-mcp` の同名conftestと衝突したため、対象を `backend/tests` に限定して実行した。
- TypeScript/ViteおよびTauri releaseビルド成功。
- インストール先のアプリ・同梱エンジンの厳密署名検証成功（ローカル用ad-hoc署名）。
- インストール先のエンジンで `native/mixxx-engine-host/tests/ddj1000.test.mjs` 成功。MIDI入力のシミュレーションと無音音源による回帰テストで、実機の操作感の再評価ではない。
- 起動後 `127.0.0.1:48123/` および `/api/tracks?limit=1` がHTTP 200。
- エンジン同梱済みDMGも作成・検証：`src-tauri/target/release/bundle/dmg/Djaly_0.4.8_aarch64.dmg`。
- 既存構成と同じくバックエンドはx86_64/Rosettaで動作する。

検証ログは `/tmp/djaly-deploy-*-20260909.log`。実曲の比較録音はローカルのみに保持し、配布物には含めていない。
