# Rekordbox MCP Server

Rekordbox のライブラリ（`master.db`、ANLZ、Cue、プレイリスト）を、Model
Context Protocol（MCP）から安全に操作するための Python サーバーです。FastMCP
サーバーと FastAPI Web API は同じドメインロジック／DB 層を共有するため、MCP
クライアントと HTTP クライアントで操作結果が分かれません。

> **注意:** 使用前に Rekordbox ライブラリ全体をバックアップしてください。書込み
> は自己責任で行い、Rekordbox を終了してから実行してください。

## 機能

- **Cue 管理**: Hot Cue、Memory Cue、Active Loop の取得・追加・更新・削除、ビート／小節へのスナップ
- **Cue 自動生成**: Phrase（PSSI）、Vocal（PVDI）、Beat Grid を使ったプロファイルベースの生成
- **プレイリスト管理**: プレイリスト／フォルダの作成、移動、改名、削除、曲の追加・削除・コピー・並べ替え、置換、重複排除
- **ChangeSet**: 差分のプレビュー、dry-run、承認後の一括反映、監査ログ、Undo/Rollback
- **3 モード**: `readonly`、`xml`、`masterdb`
- **バックアップ**: zstd 圧縮、世代・日数・容量による整理、保護、フル／差分バックアップ、復元
- **Web API / Web UI**: MCP と同じサービスを HTTP／ブラウザから利用（Web UI の起動エントリーポイントを定義）

## アーキテクチャ

```text
MCP (FastMCP) ─┐
               ├─ domain (Cue / Playlist / ChangeSet / Backup / Analysis)
Web API (FastAPI) ┘                 │
                                    ├─ db (pyrekordbox connection / repository / XML writer)
                                    └─ config (Settings / .env)
Web UI ─────────────── Web API ───────┘
```

`src/rekordbox_mcp/domain/` は入出力に依存しないドメインロジック、`db/` は
Rekordbox への接続と永続化、`mcp/` と `webapi/` はそれぞれのアダプターです。

## インストールと起動

### 前提

- Python 3.12 以上
- Rekordbox 6 または 7 と既存ライブラリ
- `uv`

```bash
cd /path/to/plumdeck/rekordbox-mcp
uv sync
cp .env.example .env   # 必要に応じて編集
```

### MCP サーバー（stdio）

```bash
uv run rekordbox-mcp --mode readonly
uv run rekordbox-mcp --mode xml
uv run rekordbox-mcp --mode masterdb
```

DB を明示する場合は `--database-path /path/to/master.db`、暗号鍵は `--db-key`、
ANLZ のディレクトリは `--db-dir` で指定できます。通常は `.env` の設定、未指定
なら自動検出が使われます。

### Web API

```bash
uv run rekordbox-webapi --mode readonly
# --host 127.0.0.1 --port 8080 で一時的に上書き可能
```

API ドキュメントは起動後の `http://127.0.0.1:8080/docs`、OpenAPI は
`/openapi.json` です。主なエンドポイントは `/api/tracks`、`/api/cues`、
`/api/playlists`、`/api/changesets`、`/api/backups`、`/api/status`、`/api/mode` です。

### Web UI

設定したホスト／ポートで起動します。

```bash
uv run rekordbox-webui
```

`pyproject.toml` には `rekordbox-webui` エントリーポイントが定義されています。
ただし、現在のソースツリーの `src/rekordbox_mcp/webui/` は空のため、UI サーバー
モジュールを含む配布物でのみこのコマンドを実行できます。UI サーバーが含まれる
構成では `REKORDBOX_WEBUI_HOST`／`REKORDBOX_WEBUI_PORT` を指定し、表示された URL を開きます。

## MCP ツール一覧

### Cue 系

| ツール | 説明 |
|---|---|
| `get_cues` | トラックの全 Cue を取得 |
| `add_hot_cue` / `add_memory_cue` / `add_loop` | Hot／Memory／Loop を追加 |
| `update_cue` | 既存 Cue を更新（`track_id` は省略時に Cue から解決） |
| `delete_cue` | Cue を削除 |
| `snap_to_beatgrid` | Beat または Bar にスナップ |
| `generate_cues` | プロファイルで Cue を生成（`replace`／`merge`／`preserve`） |
| `get_cue_profiles` / `set_cue_profile` | プロファイルの取得／切替 |

### プレイリスト系

`list_playlists`、`get_playlist_tracks`、`create_playlist`、`create_folder`、
`rename_playlist`、`move_playlist`、`delete_playlist`、`add_tracks_to_playlist`、
`remove_track_from_playlist`、`move_track_in_playlist`、`copy_track_in_playlist`、
`reorder_playlist`、`replace_playlist_tracks`、`dedupe_playlist`、
`process_playlist_cues`（プレイリスト内全曲の Cue 生成）。

### ChangeSet 系

`create_changeset`、`add_change_to_changeset`、`list_changesets`、
`preview_changeset`、`apply_changeset`（`dry_run` 対応）、`undo_changeset`、
`rollback_changeset`、`delete_changeset`、`get_audit_log`。

### バックアップ系

`backup_now`（full／differential）、`ensure_initial_backup`、`list_backups`、
`get_backup`、`protect_backup`、`restore_backup`、`restore_differential_backup`、
`cleanup_backups`、`get_backup_usage`。

### モード系

`set_mode`、`get_mode`、`get_status`。

MCP ツールは合計 46 個です（上記の Cue、プレイリスト、ChangeSet、バックアップ、
モード系を含む）。

## 3 つの動作モード

- **`readonly`**（既定）: トラック、Cue、プレイリストの読取りのみ。DB を変更する操作は拒否されます。
- **`xml`**: 書込み内容を Rekordbox Collection XML として扱うモード。Rekordbox にインポートして反映します。
- **`masterdb`**: `master.db` に直接書き込むモード。Rekordbox が起動中の場合は書込みを拒否します。

起動時は `--mode` または `REKORDBOX_MODE`、実行中は `set_mode`／`PUT /api/mode` で切り替えます。

## DB が存在しない環境での動作

Rekordbox の `master.db` が見つからない環境（`--database-path` 未指定かつ自動検出
でも見つからない場合）でも、サーバーは**エラーで落ちずに起動**します。この場合:

- `get_status` は `db_connected: false` と `db_unavailable_reason`（検出パスまたは
  「自動検出で見つからず」の理由）を返します。
- DB に依存するツール（`list_playlists`、`get_cues`、`add_hot_cue`、
  `create_playlist` など）は例外を投げず、`{"success": false, "error": "Rekordbox
  database not available: ..."}` のような graceful な失敗レスポンスを返します。
- DB に依存しない機能（`get_mode`、`set_mode`、`get_status`、バックアップ一覧など）は
  通常どおり動作します。

DB を用意したら `set_mode` でモードを切り替えるか、サーバーを再起動すると
DB 依存機能が利用可能になります。テスト用のプレースホルダ SQLite ファイルが
存在する場合は従来どおり mock バックエンドにフォールバックします。

## バックアップ

初回書込み前の保護されたフルバックアップと、操作単位の差分バックアップを作成できます。
バックアップは zstd で圧縮し、`REKORDBOX_BACKUP_MAX_DAYS`、
`REKORDBOX_BACKUP_MAX_GENERATIONS`、`REKORDBOX_BACKUP_MAX_SIZE_GB` に基づいて整理します。
保護したバックアップと最新の正常なフルバックアップは自動整理から除外されます。
`protect_backup` で保護を切り替え、`restore_backup` でフルバックアップを復元し、
`cleanup_backups` で整理、`get_backup_usage` で使用量を確認します。音声ファイルと
ANLZ ファイルはバックアップ対象外です。

## ChangeSet の使い方

1. `create_changeset` で空の ChangeSet を作る
2. `add_change_to_changeset` で変更を追加する
3. `preview_changeset` で差分を確認し、必要なら `apply_changeset(dry_run=true)` で検証する
4. 承認後 `apply_changeset` で一括反映する
5. 取り消す場合は `undo_changeset` または `rollback_changeset` を使う

監査履歴は `get_audit_log` で確認できます。

## 安全機構

- `masterdb` の DB 書込みは Rekordbox 起動中に拒否
- 書込み前に DB の整合性、バージョン、ハッシュを検証
- 初回書込み前のバックアップを確保
- ChangeSet の差分確認、dry-run、監査ログ、Undo/Rollback

それでも利用前の手動バックアップを省略しないでください。

## 設定

環境変数またはプロジェクト直下の `.env` で設定します。全項目は [.env.example](.env.example) に記載しています。
パスは `~` を展開します。`REKORDBOX_DB_PATH`、`REKORDBOX_DB_KEY`、
`REKORDBOX_DB_DIR` を省略した場合は自動検出が試みられます。

## テスト

```bash
uv run pytest tests/ -v
```

## ライセンスと upstream

本プロジェクトは MIT License（plumdeck Project, 2025）です。upstream の著作権表示と
ライセンス全文は [LICENSE](LICENSE) に収録しています。

- [pyrekordbox](https://github.com/dylanljones/pyrekordbox) — MIT、Dylan Jones
- [djcues](https://github.com/mcroydon/djcues) — BSD-3-Clause、Mike Croydon
- [Automark-for-Rekordbox](https://github.com/MichelleAppel/Automark-for-Rekordbox) — MIT
- [rekordbox-mcp](https://github.com/davehenke/rekordbox-mcp) — MIT、Dave Henke

これらのプロジェクトとは提携していません。


## MCP クライアント設定

以下の例では、プロジェクトを `/path/to/plumdeck/rekordbox-mcp`
に置いている前提です。`cwd`／`args` のパスは各環境に合わせて変更してください。
クライアントからは stdio で接続するため、サーバーの標準出力にログを出さないでください。

## 起動モード

同じ設定で `args` の `--mode` だけを変更できます。

```text
readonly: uv run rekordbox-mcp --mode readonly
xml:      uv run rekordbox-mcp --mode xml
masterdb: uv run rekordbox-mcp --mode masterdb
```

DB を自動検出できない場合は、例えば次のように追加します。

```text
--database-path /path/to/master.db --db-dir /path/to/Pioneer
```

`masterdb` で書き込む前に Rekordbox を終了し、バックアップを作成してください。

## Claude Desktop

Claude Desktop の MCP 設定（通常は `claude_desktop_config.json`）に追加します。

```json
{
  "mcpServers": {
    "rekordbox-readonly": {
      "command": "uv",
      "args": ["run", "rekordbox-mcp", "--mode", "readonly"],
      "cwd": "/path/to/plumdeck/rekordbox-mcp"
    }
  }
}
```

XML または直接 DB 書込み用に接続する場合は、`args` を次のいずれかに置き換えます。

```json
"args": ["run", "rekordbox-mcp", "--mode", "xml"]
```

```json
"args": ["run", "rekordbox-mcp", "--mode", "masterdb"]
```

### 環境変数をクライアント側で渡す例

```json
{
  "mcpServers": {
    "rekordbox": {
      "command": "uv",
      "args": ["run", "rekordbox-mcp", "--mode", "readonly"],
      "cwd": "/path/to/plumdeck/rekordbox-mcp",
      "env": {
        "REKORDBOX_DB_PATH": "/path/to/master.db",
        "REKORDBOX_MODE": "readonly"
      }
    }
  }
}
```

## Claude Code

プロジェクト直下の `.mcp.json` に記載します。

```json
{
  "mcpServers": {
    "rekordbox": {
      "type": "stdio",
      "command": "uv",
      "args": ["run", "rekordbox-mcp", "--mode", "readonly"],
      "cwd": "/path/to/plumdeck/rekordbox-mcp"
    }
  }
}
```

XML／masterdb は `args` のモードを変更して起動します。書込みモードは必要な作業時
だけ有効にすることを推奨します。

## Cursor

Cursor の MCP 設定（Settings の MCP またはプロジェクトの `.cursor/mcp.json`）に
次の形式を追加します。

```json
{
  "mcpServers": {
    "rekordbox": {
      "command": "uv",
      "args": ["run", "rekordbox-mcp", "--mode", "readonly"],
      "cwd": "/path/to/plumdeck/rekordbox-mcp"
    }
  }
}
```

クライアントによって `cwd` の扱いが異なる場合は、`args` の先頭を絶対パスの
`uv` 実行環境に合わせるか、`command` を `sh`、`args` を
`["-lc", "cd /path/to/rekordbox-mcp && uv run rekordbox-mcp --mode readonly"]`
に変更してください。


## 操作手順

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
