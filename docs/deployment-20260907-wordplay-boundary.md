# 2026-09-07 Wordplay展開境界 v0.4.5 ローカル配備記録

## 反映内容

- Wordplay候補へ前曲・次曲それぞれの展開位置を保存する。
- 実音源のBPM差を自動計算し、前曲の展開末尾、次曲の展開先頭、両Cueあり、BPM差2%以内を「実演向き」と判定する。
- 新しい候補は実演向きの条件を満たす場合だけ承認できる。既存の承認済み候補は維持する。
- Cueが曲尺外の場合と、REST APIの真偽値を数値として渡した場合を拒否する。
- Wordplay画面に展開位置、各BPM、BPM差、条件合否を表示する。

## 検証

- バックエンド全227テストが成功した。
- TypeScript/Vite本番ビルドとTauri v0.4.5リリースビルドが成功した。
- 更新前DBを `~/Library/Application Support/Djaly/backups/20260907-before-boundary-v0.4.5/djaly.duckdb` に保存し、元DBとSHA256が一致した。
- 更新前アプリを `/Applications/Djaly-0.4.4-backup-20260907-boundary.app` に保存した。
- `/Applications/Djaly.app` の署名検証、v0.4.5表示、API起動、既存DBへの列追加、厳密入力検証を確認した。
- GitHubへの公開・アップロードは行っていない。
