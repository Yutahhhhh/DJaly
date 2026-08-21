# 操作手順書

## 事前準備

1. Rekordbox を終了する（読み取りだけなら起動中でも利用できます）。
2. Rekordbox ライブラリ全体を手動バックアップする。
3. `.env` の DB パス、モード、バックアップ先を確認する。
4. `uv run rekordbox-mcp --mode readonly` で接続し、`get_status` を実行する。

## Cue の取得・追加・更新・削除

1. `get_cues(track_id)` で現在の Hot Cue、Memory Cue、Loop を確認する。
2. `add_hot_cue`、`add_memory_cue`、または `add_loop` に `track_id` と位置（ミリ秒）を渡す。
   位置は Beat Grid にスナップされます。
3. `update_cue_with_track(track_id, cue_id, ...)` で名前、位置、色、ループ終端を更新する。
   `update_cue` は現在 `track_id` を受け取れないため使用しません。
4. `delete_cue(cue_id, track_id)` で削除する。
5. 既存 Cue の位置を直す場合は `snap_to_beatgrid(track_id, cue_id, grid="beat" または "bar")` を使う。

書込みは `xml` または `masterdb` モードで行います。`masterdb` では Rekordbox を終了してください。

## Cue の自動生成

1. 対象トラックに Beat Grid、Phrase（PSSI）、Vocal（PVDI）の解析データがあることを確認する。
2. `get_cue_profiles` でプロファイルを確認し、必要なら `set_cue_profile` で切り替える。
3. `generate_cues(track_id, profile="default", mode="replace")` を実行する。
   既存 Cue を残す場合は `merge`、既存位置を保護する場合は `preserve` を使う。
4. プレイリスト全体には `process_playlist_cues(playlist_id, mode=...)` を使う。

生成結果の `confidence` と `notes` を確認してから、必要なら ChangeSet で反映する運用を推奨します。

## プレイリストの作成・管理

1. `create_folder(name, parent_id="root")` でフォルダを作る。
2. `create_playlist(name, parent_id=...)` でプレイリストを作る。
3. `add_tracks_to_playlist(playlist_id, track_ids, position=...)` で曲を追加する。
4. `list_playlists` と `get_playlist_tracks` で構成を確認する。
5. `reorder_playlist`、`move_track_in_playlist`、`copy_track_in_playlist` で順序を調整する。
6. `remove_track_from_playlist`、`replace_playlist_tracks`、`dedupe_playlist` で整理する。
7. `rename_playlist`、`move_playlist`、`delete_playlist` で階層を管理する。

## ChangeSet で安全に変更する

1. `create_changeset("説明")` で ChangeSet を作る。
2. `add_change_to_changeset` に action（`create`／`update`／`delete`／`replace`／`merge`）、
   対象、`old_data`、`new_data` を追加する。
3. `preview_changeset(changeset_id)` で差分を人間が確認する。
4. `apply_changeset(changeset_id, dry_run=true)` で検証する。
5. 問題がなければ `apply_changeset(changeset_id)` を実行する。
6. 取り消す場合は `undo_changeset` または `rollback_changeset` を実行する。
7. `get_audit_log(changeset_id=...)` で履歴を確認する。

## バックアップの作成・保護・復元・整理

```text
ensure_initial_backup()                         # 初回の保護フルバックアップ
backup_now(type="full", description="before cue edit")
backup_now(type="differential", entity_type="cue", entity_ids=[...])
list_backups()
get_backup_usage()
protect_backup(backup_id, protect=true)
restore_backup(backup_id)
cleanup_backups()
```

差分バックアップは `entity_type` と `entity_ids` が必須です。フルバックアップを復元する前に
対象 DB の現在状態も別名で保存し、Rekordbox を終了してください。差分の復元は
`restore_differential_backup` でレコードを取得し、内容を確認してから手動適用します。

## モード切替

- 起動時: `uv run rekordbox-mcp --mode readonly|xml|masterdb`
- MCP: `get_mode` で確認し、`set_mode(mode="xml")` などで切替
- Web API: `GET /api/mode` で確認し、`PUT /api/mode` に `{"mode":"xml"}` を送る

モード変更時はサービスが再初期化されます。書込み終了後は `readonly` に戻してください。

## Web UI / Web API

1. `uv run rekordbox-webapi --mode readonly` を起動する。
2. ブラウザから `http://127.0.0.1:8080/docs` を開き、API の疎通と状態を確認する。
3. Web UI サーバーモジュールを含む配布物では `uv run rekordbox-webui` を別ターミナルで起動し、
   設定された `REKORDBOX_WEBUI_HOST`／`REKORDBOX_WEBUI_PORT` の URL を開く。なお、現在の
   ソースツリーの `src/rekordbox_mcp/webui/` は空であるため、この checkout 単体では UI は起動できない。
4. Cue、プレイリスト、ChangeSet、バックアップを UI から操作する場合も、まず readonly で確認し、
   反映時だけ xml／masterdb に切り替える。
