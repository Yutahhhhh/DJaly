# MCP歌詞登録（v0.4.3）

`register_track_lyrics(track_id, content, source="user", language=null, overwrite=false)`
で1曲、`register_track_lyrics_batch(items, overwrite=false)`で1〜100曲を登録する。
itemsは同じtrack_id/content/source/languageのオブジェクト配列。

- search_tracksで曲IDを確認してから、手元の歌詞本文やLRCを渡す。
- DBへの保存のみ。音源タグには書き込まない。
- 既存の空でない歌詞はskipped_existing。意図的な置換はoverwrite=true。
- 出典はsourceに記録する（例：local:lrc、local:metadata）。languageは任意。
- 入力不正、曲ID不在、重複IDではバッチ全体を登録しない。
- 結果は曲IDとcreated/updated/skipped_existing/unchangedを返す。
- 置換時は歌詞キーワードキャッシュを無効化する。
- 保存した本文はget_track_lyrics、検索はsearch_lyricsで確認できる。

外部歌詞サービスの取得処理は、この登録ツールには含まれない。

## 手元の歌詞を取り込む

```sh
backend/.venv/bin/python scripts/import_local_lyrics.py --report /tmp/local-lyrics-scan.json
backend/.venv/bin/python scripts/import_local_lyrics.py --apply --report /tmp/local-lyrics-import.json
```

指定ジャンルの歌詞未登録曲に対し、同名LRC、MP3のUSLT、MP4の歌詞、
FLAC等の歌詞タグを調べる。インスト／カラオケ表記は除外する。
標準では調査のみ。`--apply`でMCP登録し、保存内容を再取得して一致を確認する。
レポートは曲ごとの結果と出典・内容ハッシュを保存し、歌詞本文は含めない。

## 2026-09-06 ローカル配備・調査結果

- `/Applications/Djaly.app`をv0.4.3へ更新。GitHub公開は実施していない。
- 全192バックエンドテストとTypeScript/Vite・Tauri/PyInstallerビルドが成功。
- ローカル署名を検証し、一時DBとインストール後の本番アプリでMCP登録ツール2つを確認した。
- 旧アプリは`/Applications/Djaly-0.4.2-backup-20260906-lyrics.app`に保存。
- DBとWALはプロセスのDBロック解放後にコピーし、SHA256一致を確認した。
  バックアップ先：`~/Library/Application Support/Djaly/backups/20260906-before-lyrics-registration/`。
  解析キューはSQLite Backup APIを使用し、integrity_check=ok。
- `lyrics-import.json`に曲単位の調査結果を保存した。
- 調査時点の25,084曲中、歌物ジャンル／サブジャンルの対象は13,663曲。
  登録済み3,210曲、ローカル歌詞なし10,273曲、音源不在172曲、インスト等除外8曲。
  新規登録0件。外部サイトからの歌詞取得は実行していない。
- 調査中にもライブラリの曲数が増えていたため、件数は一覧取得時点のスナップショット。
- 一覧取得はHTTP APIを使用した。既存のMCP検索は歌詞本文も返すため大きな応答が
  途切れる場合があり、登録日時だけで並べるページ取得にも重複が発生した。
  登録・保存内容の検証にはMCPを使用する。今回、登録対象は見つからなかった。
