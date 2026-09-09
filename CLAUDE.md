# Djaly

ローカルファーストの音楽ライブラリ管理 / DJツール。Tauri + React フロント、FastAPI バックエンド、Essentia / MusiCNN によるローカル音響解析。**Djaly 自身は LLM を一切呼ばない** — ジャンル分類も自然言語解釈も、MCP で接続したクライアント（＝このセッション）が推論を担う。

## コマンド

```bash
pnpm install                 # フロント依存
cd backend && ./setup.sh     # バックエンド依存
pnpm backend:dev             # FastAPI (:8001, ホットリロード)
pnpm tauri dev               # デスクトップアプリ
pnpm release v0.1.0          # リリース（pyinstaller → sidecar → tauri build → gh release）
```

ブランチは GitHub Flow（`main` / `feature/*` / `fix/*` / `refactor/*` / `chore/*`）。詳細は `docs/development-workflow.md`。

## MCP サーバー

`.mcp.json` に2つ定義してある。

- **djaly** — `http://127.0.0.1:48123/mcp`。アプリまたは `pnpm backend:dev` が動いている間だけ到達できる。
- **rekordbox** — `rekordbox-mcp --mode readonly`、`master.db` を参照。読み取り専用で起動しているので rekordbox 側を壊す操作はできない。

同じ `djaly` が `~/.claude.json` のローカルスコープにも登録されており、そちらが優先される。`.mcp.json` はリポジトリに残す可搬な定義として置いている。`.mcp.json` の新規サーバーは次回セッション開始時に承認プロンプトが出る。

### Djaly MCP の扱い方

**推論はこちら側の仕事。** 「エモい深夜のハウス」のような雰囲気を、BPM・energy・danceability・brightness の具体的な範囲へ翻訳してから `search_tracks` に渡す。Djaly は渡された条件で決定的に検索するだけで、曖昧な語を解釈しない。

**id が要る。** ミューテーション系ツールは track id / setlist id を要求する。タイトル文字列では動かない。存在を仮定せず `search_tracks` や `list_setlists` を先に呼び、返ってきた id を使う。

**ジャンル分類のフロー** — `get_genre_analysis_context` で対象曲と既存ラベルの文脈を取得 → **こちらが分類を決める** → `apply_genre_analysis`（単体）または `apply_genre_analyses`（一括）で適用。ラベル整理は `get_genre_cleanup_suggestions` → `cleanup_genre_labels`。現在ライブラリにあるのは 20 ジャンル（African / Afrobeats / Bass / Country / Dance / Downtempo / Electronic / Funk / Hip Hop / House / Jazz / Latin / Other / Pop / R&B / Reggae / Rock / Techno / Trance / Trap）。

**ワードプレイ** — `get_track_lyrics` / `search_lyrics` で歌詞を実際に読み、**こちらがフレーズを選び**、`find_wordplay_links` で繋がりを引く。セットリストへの反映は `add_track_to_setlist_with_wordplay` / `update_setlist_track_wordplay` / `clear_setlist_track_wordplay`。

**音響再解析** — `plan_track_analysis` で影響範囲を見てから `start_track_analysis`。既定は embedding-only かつ `only_outdated`：既存タグを保持し無駄な再計算を避けるため。ジョブは永続的なので `get_track_analysis_status` / `pause_track_analysis` / `resume_track_analysis` で監視・中断・再開する。

**エクスポート** — `validate_setlist_export` で欠損ファイル等を確認してから `export_setlist_m3u8`。

**共有状態であることを忘れない。** セットリスト、ジャンル適用、解析ジョブはすべて永続的で、アプリの UI からも見えている。同じセットリストや同じジョブに対して複数のエージェントが並行して書き込まない（`~/.claude/delegation.md` の直列化ルール）。

**曲は聴けない。** ファイル名・タグ・特徴量から推測はできるが、実際に音を聴いた判断はできない。「確認した」と書かない。

### 既知のドリフト（2026-09-07 時点）

ソースには 45 個の `@mcp.tool()` があるが、`:48123` で動いているサーバーは 39 個しか公開していない。未公開の 6 個は、作業ツリー側の新規/変更ファイルに由来する。

| ツール | 定義元 |
| --- | --- |
| `list_wordplay_pairs` / `propose_wordplay_pairs` / `approve_wordplay_pair` / `reject_wordplay_pair` | `backend/mcp_server/tools/wordplay.py`（未追跡の新規ファイル） |
| `register_track_lyrics` / `register_track_lyrics_batch` | `backend/mcp_server/tools/lyrics.py`（変更あり） |

これらを使うにはバックエンドを再起動する必要がある。逆に、再起動していない状態でこれらのツール名を前提にした手順を書かない。

## ハーネス

タスクの委譲方針・役割・モデルルーティングはグローバル側にある：`~/.claude/CLAUDE.md`（ルーティングとコンテキスト予算）、`~/.claude/delegation.md`（委譲手順、委譲直前に読む）、`~/.claude/model-routing.md`（モデルと effort の根拠）。役割定義は `~/.claude/agents/task-{light,analyze,implement,review,hard}.md`。
