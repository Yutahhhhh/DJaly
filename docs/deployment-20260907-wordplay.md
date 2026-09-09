# 2026-09-07 Wordplay 機能ローカル配備記録

## 配備

- このMacの`/Applications/Djaly.app`をv0.4.4へ更新した。GitHub公開リリース・アップロードは実施していない。
- 更新前のv0.4.3を`/Applications/Djaly-0.4.3-backup-20260907-wordplay.app`へ退避した。
- 停止中のDBを`/Users/horiyuuta/Library/Application Support/Djaly/backups/20260907-before-wordplay-v0.4.4/djaly.duckdb`へバックアップした。
- 更新前DBとバックアップのSHA256は共に`93f5f50ac405cb7c8371d8b2122e0fbc68ba4a31682781e84c3b649644df2c0d`。
- PyInstaller sidecarとTauriアプリをビルドし、ローカル用ad-hoc署名を付与した。インストール先の厳密署名検証に合格している。

## 反映内容

- MCPクライアントから方向付きワードプレイ候補を複数提案し、永続的な承認待ち候補として登録できる。
- アプリのWordplay画面で承認待ち・承認済み・全件を確認、検索、承認、検証状態の更新、却下による物理削除ができる。
- 承認済みの組み合わせはセットリスト候補生成とWordタブで再利用され、接続情報もセットリストへ保存される。
- MCPには`list_wordplay_pairs`、`propose_wordplay_pairs`、`approve_wordplay_pair`、`reject_wordplay_pair`を追加した。

## 検証

- Djalyバックエンド全208テストが通過した（Pydanticの既知の非推奨警告1件）。
- TypeScript/Vite本番ビルドとTauriリリースビルドが成功した。
- インストール版v0.4.4を起動し、`127.0.0.1:48123`のAPI待受、`GET /api/wordplay-pairs`、実MCP接続で全45ツール中4つのWordplayツール公開を確認した。
- インストール版のWordplay画面を実際に開き、フィルター、検索、空状態が表示されることを確認した。
- x86_64 sidecarをarm64 MacでRosetta実行する現行構成のため、更新直後の初回起動ではAPI待受まで約90秒かかった。起動完了後の疎通は正常。

