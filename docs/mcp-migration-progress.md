# MCP 中心アプリへの改修状況

更新日: 2026-08-21

## 1. 目標

Djaly を、画面上で検索条件や生成プロンプトを細かく操作するアプリから、外部の MCP クライアントを主な操作入口とするアプリへ移行する。

- Claude Desktop / Claude Code などの外部 MCP クライアントから Djaly を操作する。
- 楽曲検索、セットリスト作成、ジャンル・歌詞解析など、MCP で完結できる操作は原則 MCP ツールへ移す。
- Djaly の UI は成果物、進捗、ライブラリ状態を確認するための表示を中心にする。
- MCP の接続情報、設定方法、利用可能なツールは専用ページで確認できるようにする。
- 既存機能を一度に削除せず、MCP で代替できることを確認してから操作 UI を段階的に縮小する。

## 2. 現在の実装状況

### 2.1 MCP サーバー基盤

実装済み。

- Python MCP SDK の `MCPServer` を使用。
- FastAPI バックエンドに Streamable HTTP としてマウント。
- 接続先は開発環境で `http://127.0.0.1:8001/mcp`、本番ビルドで `http://127.0.0.1:48123/mcp` を想定。
- DB 操作は既存のサービス層と DuckDB を再利用。
- SQLModel / Pydantic の返却値を MCP の構造化レスポンスへ変換。
- FastAPI の lifespan が複数回起動されるテスト環境でも動作するよう、MCP の session manager を起動ごとに再生成。
- `backend/requirements.txt` に `mcp` を追加。
- PyInstaller の hidden imports と収集対象に MCP 関連パッケージを追加。

主なファイル:

- `backend/mcp_server/instance.py`
- `backend/mcp_server/server.py`
- `backend/mcp_server/tools/`
- `backend/main.py`
- `backend/djaly-server.spec`

### 2.2 MCP ツール

現在 36 ツールを登録済み。

#### 楽曲・検索: 6 ツール

- `search_tracks`: 文字列、ジャンル、BPM、キー、年代、音響特徴量、歌詞状態などで検索
- `vibe_search`: 自然言語を特徴量へ解決して検索
- `get_track_similar`: 音響ベクトルによる類似曲検索
- `suggest_track_genre`: 類似曲からジャンル候補を推測
- `update_track_genre`: ジャンル更新
- `update_track_info`: タイトル、アーティスト、アルバム、年の更新

#### セットリスト: 17 ツール

- 一覧、作成、名称変更、削除
- 曲一覧の取得、一括置換、追加、削除
- 次曲提案
- `generate_auto_setlist`: 自然言語の vibe 説明文に基づきセットリスト候補を自動生成（曲数は length / min_length〜max_length / UI 設定のデフォルト曲数で解決）
- `recommend_next_track`: 指定曲の次に繋ぐ曲を提案（任意の vibe 説明文で方向性を指定可能）
- 開始曲と終了曲を結ぶ Bridge 生成
- M3U8 出力と出力前検証
- `add_track_to_setlist_with_wordplay`: wordplay メタデータ付きで曲を追加
- `update_setlist_track_wordplay`: セットリスト内の曲の wordplay 情報を更新
- `clear_setlist_track_wordplay`: セットリスト内の曲の wordplay 情報をクリア
- `generate_wordplay_setlist`: 歌詞キーワード一致で繋ぐセットリスト自動生成

※ プロンプト・プリセット系は 2026-08-21 に全廃止。MCP クライアント側の LLM が直接 vibe 説明文を生成するため、保存されたプロンプト/プリセットは不要になった。

#### ジャンル解析・整備: 9 ツール

- ジャンル、サブジャンル一覧
- 未解析曲一覧
- 単曲および複数曲の LLM ジャンル解析
- 表記揺れ候補の取得と統一
- 類似曲によるジャンル候補取得
- DB のジャンル情報を実ファイルへ反映

#### 歌詞・ワードプレイ: 4 ツール

- 歌詞取得
- LLM によるワードプレイ候補抽出
- 歌詞横断検索
- `find_wordplay_links`: 指定曲のキーワード解析と、各キーワードを含む他曲を繋ぎ候補として返す

### 2.3 MCP 設定ページ

実装済み。

- サイドバーに `MCP` ページを追加。
- 接続 URL と接続可否を表示。
- Claude Desktop / Claude Code 向けの設定例を表示。
- 接続 URL のコピー機能を提供。
- バックエンドから登録済み MCP ツール一覧を取得して表示。
- `GET /api/mcp/info` でサーバー情報とツール一覧を返す。

主なファイル:

- `backend/api/routers/mcp_info.py`
- `src/components/mcp-view/McpView.tsx`
- `src/services/mcp.ts`
- `src/components/sidebar/Sidebar.tsx`
- `src/App.tsx`

### 2.4 現時点の UI

既存 UI の削除・縮小はまだ行っていない。

以下は従来どおり操作可能な状態を残している。

- Music Library の検索・フィルタ UI（プリセット選択は廃止し、vibe フリーテキスト入力に変更）
- Prompt Manager は廃止（MCP クライアントの LLM が vibe を直接生成するため）
- Setlist Creator と Auto / Word / Bridge 系の操作 UI（プリセット選択は廃止し、vibe フリーテキスト入力に変更）
- File Explorer と取り込み操作
- Tag Manager、ジャンル解析、メタデータ・歌詞操作
- Settings の LLM・インポート・エクスポート操作

理由は、MCP ツールを実クライアントと実データで検証する前に既存導線を削除すると、機能にアクセスできなくなるリスクがあるため。MCP で同等以上の操作が確認できた領域から順に縮小する。

## 3. 実施済みの確認

### 3.1 MCP プロトコル疎通

一時 DB とバックエンドを使用して以下を確認済み。

- `initialize` が成功し、サーバー名 `Djaly` と capabilities を返す。
- `tools/list` が成功し、登録ツールを返す。
- `search_tracks` の MCP 呼び出しが成功する。
- `list_setlists` の MCP 呼び出しが成功する。
- 既存 REST API の `/api/tracks/count` と `/api/` が MCP マウント後も応答する。
- `/api/mcp/info` が接続 URL と 39 ツールを返す。

### 3.2 回帰チェック

2026-08-21 時点で以下を確認済み。

```text
backend/.venv/bin/pytest -q
109 passed, 1 warning

npx tsc --noEmit
成功

npx vite build
成功
```

警告は既存の Pydantic Config 非推奨警告と Vite の chunk size / dynamic import 警告。今回の MCP 改修によるテスト失敗やビルドエラーは残っていない。

### 3.3 MCP 専用テスト

2026-08-21 に MCP サーバー専用の自動テスト 31 件を追加した。

- テストファイル: `backend/tests/test_mcp_server.py`
- 実 MCP クライアント（`mcp.client.session.ClientSession` + `streamable_http_client`）を httpx2 の ASGITransport 経由で FastAPI アプリに接続し、プロトコルレベルで検証する方式。
- 検証内容:
  - `initialize`（サーバー名 Djaly、protocolVersion、capabilities）
  - `tools/list`（39 ツールの登録確認）
  - 主要 read ツール: search_tracks / vibe_search / get_track_similar / suggest_track_genre / list_setlists / list_prompts / list_presets / list_genres / list_subgenres / get_unknown_genre_tracks / get_track_lyrics / search_lyrics
  - 主要 write ツール: update_track_genre / update_track_info / create・rename・delete_setlist / add・remove・set_setlist_tracks / export_setlist_m3u8 / validate_setlist_export / プロンプト・プリセット CRUD / analyze_track_genre
  - エラー応答: 未知ツール、存在しない ID、必須引数欠落
  - E2E: 検索 → セットリスト作成 → 一括置換 → M3U8 エクスポート
- テスト実行結果: `backend/.venv/bin/pytest -q` で **140 passed**（既存 109 + 新規 31）。
- テスト実装に伴う修正:
  - `backend/mcp_server/instance.py`: `from infra.database.connection import engine`（import 時束縛）を `from infra.database import connection` + `Session(connection.engine)` の遅延アクセスに変更した。テストで engine を差し替えても MCP ツールが実 DB を触らないようにするため。
  - `backend/mcp_server/server.py`: `build_mcp_asgi_app()` / `MCPAppHolder` に `transport_security` パラメータを追加した（テスト環境の Host ヘッダー検証を緩和するため。本番デフォルト挙動は不変）。

### 3.4 プロンプト/プリセット廃止とワードプレイ MCP 整備

- 2026-08-21 にプロンプト/プリセット系を全廃止した（MCP ツール 8 件、REST API、Prompt Manager UI、プリセット選択 UI、サービス・モデル・シード・DB テーブル）。
- 理由: MCP クライアント側の LLM が直接 vibe 説明文を生成できるため、保存されたプロンプト/プリセットは不要。
- `generate_auto_setlist` / `recommend_next_track` を `preset_id` → `vibe`（自然言語）引数に変更。曲数は `length` / `min_length`〜`max_length` / UI 設定 `setlist_default_length`（デフォルト 10）の順で解決。
- ワードプレイ MCP ツール 5 件を追加（find_wordplay_links / add_track_to_setlist_with_wordplay / update_setlist_track_wordplay / clear_setlist_track_wordplay / generate_wordplay_setlist）。
- MCP ツール総数は 39 → 36。
- テスト: `backend/.venv/bin/pytest -q` で **134 passed**。`npx tsc --noEmit` / `npx vite build` 成功。

## 4. 未完了・未検証

### 4.1 解析・取り込み系の MCP 化

ジャンル解析と歌詞ワードプレイ解析は MCP 化済みだが、以下は未実装。

- 音楽ディレクトリ・ファイル一覧の取得
- 新規ファイルの取り込み、再解析、解析キャンセル
- 音響特徴量解析の進捗・完了状態取得
- リリース年、歌詞、アートワークなどのメタデータ自動取得
- メタデータ一括更新の開始、進捗取得、キャンセル
- 解析キャッシュの確認・クリア
- ジャンル一括バックグラウンド解析の開始、状態取得、キャンセル

長時間処理を MCP ツールから同期実行するとタイムアウトしやすい。開始ツールは `task_id` を返し、別の状態取得ツールとキャンセルツールを用意する非同期ジョブ方式を基本とする。

### 4.2 設定・データ管理系の MCP 化

以下は未実装。

- LLM プロバイダー・モデル設定の参照と更新
- LLM 接続テスト
- ライブラリ、メタデータ、プリセットのインポート・エクスポート
- M3U8 の実ファイル保存先指定と保存
- OS 上でのファイル表示など、明示的なユーザー確認が必要な操作

API キーなどの秘密値は MCP 応答に返さない。更新操作も、ログやツール結果へ値を露出しない設計が必要。

### 4.3 UI の表示中心化

未着手。

- Library: 複雑な検索ダイアログを縮小し、一覧、MCP 結果のハイライト、再生、詳細確認を中心にする。
- Setlists: 手動編集機能をどこまで残すか決定し、生成結果・曲順・遷移品質・エクスポート状態の確認を中心にする。
- Prompts: 廃止済み（2026-08-21）。MCP クライアントの LLM が vibe を直接生成するため。
- Tags: 解析の開始操作を MCP に移し、進捗、差分、失敗曲、反映結果の確認を中心にする。
- Explorer: ディレクトリ選択など OS UI が必要な操作だけ残し、解析開始は MCP へ移す。
- Settings: ローカル秘密情報と OS 依存設定だけ UI に残すかを整理する。
- Dashboard: MCP による直近操作、実行中ジョブ、成果物への導線を追加する。

### 4.4 実利用・配布形態の検証

未実施。

- Claude Desktop からの実接続
- Claude Code からの実接続
- 表示しているクライアント設定例が各クライアントの現行仕様と一致するか
- 実ライブラリでの検索、編集、解析、セットリスト作成の一連の操作
- Tauri 開発版を起動した状態での接続
- PyInstaller による sidecar 実ビルド
- Tauri リリースビルド内の sidecar からの接続
- macOS / Windows それぞれの localhost、ファイアウォール、終了処理
- MCP クライアント接続中に Djaly を終了・再起動した場合の再接続

## 5. 次に進める順序

### Phase 1: MCP 基盤を製品として成立させる

1. MCP 専用テストを追加する。 → 実施済み (2026-08-21, 31 件)
2. `initialize`、`tools/list`、主要 read/write ツール、エラー応答を自動テストする。 → 実施済み (2026-08-21)
3. 実 DB で、楽曲検索からセットリスト保存までの E2E シナリオを確認する。
4. Claude Desktop / Claude Code へ実登録し、設定ページの手順を修正する。
5. PyInstaller sidecar と Tauri リリースビルドで MCP パッケージが確実に同梱されることを確認する。
6. ローカルホスト限定、Origin / Host 制限、破壊的操作の確認方針を点検する。

### Phase 2: 解析系を MCP へ移す

1. 共通のバックグラウンドジョブ表現を決める。
2. `start_ingestion`、`get_ingestion_status`、`cancel_ingestion` を追加する。
3. `start_metadata_update`、`get_metadata_status`、`cancel_metadata_update` を追加する。
4. `start_genre_analysis`、`get_genre_analysis_status`、`cancel_genre_analysis` を追加する。
5. 単曲の音響再解析、歌詞取得、年取得など個別ツールを追加する。
6. MCP クライアントが完了までポーリングでき、失敗曲と理由を取得できるようにする。

### Phase 3: 残りの管理機能を MCP へ移す

1. LLM 設定の安全な参照・更新・接続テストを追加する。
2. インポートは「解析」「差分確認」「実行」を別ツールに分ける。
3. エクスポートは成果物を返す処理と、ローカル保存を分離する。
4. ファイル書き込み、タグ反映、削除など副作用の大きいツールへ destructive hint と明確な説明を付ける。

### Phase 4: UI を成果物表示中心へ刷新する

1. MCP で代替済みの操作と未代替の操作を画面ごとに一覧化する。
2. 代替済み機能の操作 UI を縮小し、「MCP で操作」の説明と設定ページへの導線を配置する。
3. 一覧、詳細、再生、進捗、差分、エラー、生成結果の表示を改善する。
4. 既存コンポーネントを即削除せず、E2E 確認後に未使用コードとサービスを整理する。
5. デスクトップと小さい画面の双方でレイアウトを確認する。

### Phase 5: 最終機能チェック

以下をすべて確認してから UI 削除を完了扱いにする。

- 楽曲の取り込み、再解析、キャンセル、進捗確認
- 楽曲一覧、フリーテキスト検索、全フィルタ、Vibe 検索、ページング
- 楽曲情報・ジャンルの更新、類似曲、ジャンル候補
- 単曲・一括ジャンル解析、表記揺れ統一、ファイルタグ反映
- 歌詞取得、歌詞検索、ワードプレイ解析
- プロンプトとプリセットの CRUD（廃止済み）
- セットリストの CRUD、曲順更新、追加・削除
- 次曲提案（vibe 指定可）、自動生成（vibe + 曲数指定）、Bridge 生成、ワードプレイ生成
- M3U8 の検証、生成、保存、Rekordbox 読み込み
- LLM 設定、接続テスト、プロバイダー切替
- ライブラリ・メタデータ・プリセットのインポートとエクスポート
- Dashboard と各バックグラウンド進捗表示
- 音楽再生、アートワーク、ファイル表示など UI に残す機能
- MCP クライアント未接続時でも成果物を UI で閲覧できること
- MCP エラー、LLM エラー、DB エラー、存在しない ID、キャンセル時の表示
- 開発版、PyInstaller sidecar、Tauri リリース版での動作
- `pytest`、`tsc --noEmit`、`vite build`、Tauri ビルド

## 6. 現時点の設計上の注意

- MCP は `127.0.0.1` 向けで、外部ネットワーク公開を前提にしない。
- 現状は認証なし。ホストを外部公開する変更を行う場合は認証と権限制御が必須。
- 更新・削除・実ファイル書き込み系ツールは、読み取りツールより慎重に扱う。
- 長時間解析は同期 MCP 呼び出しへ詰め込まず、開始・状態取得・キャンセルに分割する。
- REST API と MCP の双方から同じサービス層を使い、処理の二重実装を避ける。
- UI を削る前に MCP の同等機能、エラー処理、進捗確認が揃っていることを確認する。

## 7. Git 作業ツリーについて

今回の MCP 改修ファイルはまだコミットされていない。

また、以下の未追跡ファイルは MCP 改修とは無関係と判断しており、変更・削除していない。

- `House_Peak_Hour_Sets_2026-06-09.m3u8`
- `House_Peak_Hour_Sets_2026-06-09_match_report.md`
