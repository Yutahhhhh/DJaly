# 03. ユーザビリティ改善一覧

対象範囲: `src/` 全般。コードを精査して確認できた UI/UX 上の問題と、具体的な改修方法。

---

## UX-01: エラー通知基盤の導入（最優先・他項目の前提）

**対象**: アプリ全体。現状の代表例:
- `src/components/setlist-creator/tabs/AutoTab.tsx:104,129` — `alert("Generation failed.")`（原因不明のネイティブダイアログ）
- `src/components/setlist-creator/SetlistCreator.tsx:109` — セットリスト保存失敗が `console.error` のみ（**ユーザーは保存されたと思い込む**）
- `src/components/music-library/useTrackSearch.ts:44` — 検索失敗が `console.error` のみ
- `src/components/setlist-creator/tabs/WordTab.tsx:81` — 歌詞ロード失敗が無通知

**改修内容**:
1. `sonner`（shadcn/ui 標準のトースト）を導入: `pnpm add sonner`、`App.tsx` に `<Toaster richColors position="bottom-right" />` を配置。
2. `api-client.ts` を BUG-14 の `ApiError`（status + detail 保持）に改修した上で、各 catch 節を置換:
```tsx
import { toast } from "sonner";
catch (e) {
  toast.error("セットリストの保存に失敗しました", {
    description: e instanceof ApiError ? e.detail : String(e),
  });
}
```
3. LLM 設定不備（`CONFIG_ERROR: API Key ...`）の detail はそのまま表示すれば、ユーザーが Settings へ行く動線になる。detail に `CONFIG_ERROR` を含む場合は「Settings を開く」アクションボタン付きトーストにする。

**置換対象の検索方法**: `grep -rn "console.error\|alert(" src/components src/services` の各箇所を仕分けし、ユーザー操作起点の失敗はすべてトースト化する。

---

## UX-02: Vibe 検索の進行状態と AI 解釈結果の可視化

**対象**: `src/components/music-library/FilterDialog.tsx`、`MusicLibrary.tsx`、`useTrackSearch.ts`

**現状**: vibe_prompt 付き検索は LLM 待ちで数秒〜数十秒かかるが、通常検索と同じローディング表示しかなく、**AI がプロンプトをどう解釈したかも見えない**。結果が変なときにプロンプトを直すべきか判断できない。

**改修内容**（BUG-07 の「2段階 API 分離」とセットで実施）:
1. `POST /api/vibe/resolve` を新設し、`{prompt}` → `{bpm, energy, danceability, brightness, year_min, year_max}` を返す。
2. フロントは resolve 完了までは「AI が雰囲気を解析中…」スピナー、完了後に解釈結果をバッジ列で表示:
```
Mood: "夜のドライブチル" → BPM~92 / Energy 0.35 / Dance 0.6 / 〜
```
3. 各バッジは編集可能（クリックでスライダー）にし、AI 解釈を微調整して再検索できるようにする。`FilterState` に解決済みパラメータを保持し、ページネーションは通常のパラメータ検索として行う（LLM 再実行なし）。

---

## UX-03: ライブラリの総件数表示と検索結果カウント

**対象**: `src/components/music-library/MusicLibrary.tsx:112-114`

**現状**: `{tracks.length} tracks loaded` は「読み込み済み件数」であり、検索条件に合う総数がわからない。無限スクロールでどこまであるのか見当がつかない。

**改修内容**:
1. バックエンドに `GET /api/tracks/count`（`_apply_search_conditions` を再利用して `select(func.count())`）を追加。
2. `useTrackSearch` で検索条件変更時に並行で count を取得し、`{tracks.length} / {totalCount} tracks` と表示。
3. 0件時は「条件に一致する曲がありません。フィルタをクリア」ボタンを TrackList の empty state に表示する。

---

## UX-04: 解析(Analyze)ボタンの進捗フィードバック

**対象**: `src/components/music-library/MusicLibrary.tsx:80-93`、`src/contexts/IngestionContext.tsx`

**現状**: BUG-13 の通り、解析開始直後にリスト更新してしまい結果が反映されない。さらに解析中であることが行単位でわからない。

**改修内容**:
1. `IngestionContext` の WebSocket 進捗 (`type: "complete"`) を購読し、完了時に `search(true)` + 「解析が完了しました」トースト。
2. 解析中の行には spinner アイコンとともに `analyzingId` を維持（現在は ingest API 応答で即解除されている）。
3. 複数曲同時解析に備え `analyzingId: number | null` を `Set<number>` に変更。

---

## UX-05: セットリスト編集の Undo と保存状態インジケーター

**対象**: `src/components/setlist-creator/SetlistCreator.tsx`

**現状**: 曲削除・並べ替えは即 DB 反映で取り消し不可。保存中/保存済みの表示もないため、保存失敗（UX-01 参照）に気づけない。

**改修内容**:
1. `commitTracksToDB` 実行中は `saving` state を立て、ヘッダーに「Saving… / Saved ✓」を表示（BUG-11 の直列化キューと同時に実装）。
2. 軽量 Undo: 直近 20 操作分の `tracks` スナップショットをスタックに積み、`Cmd+Z` で `commitTracksToDB(previousSnapshot)`。dnd-kit のドラッグとは独立に実装できる。
3. 曲削除時はトーストに「元に戻す」アクションを付ける（sonner の action オプション）。

---

## UX-06: AutoTab（自動生成）の説明不足の解消

**対象**: `src/components/setlist-creator/tabs/AutoTab.tsx`

**現状の問題**:
1. Infinite Flow は**セットリスト末尾3曲を暗黙的にシード**にする（`currentSetlistTracks.slice(-3)`）が、UI に一切表示がない。空のセットリストとそうでない場合で結果が大きく変わる理由がユーザーに見えない。
2. プリセット未作成の場合、Select が disabled になるだけで「Prompt Manager でプリセットを作る」導線がない。
3. 生成結果に遷移品質（BPM 差・キー相性）の根拠表示がない。

**改修内容**:
1. シード表示: `currentSetlistTracks.length > 0` のとき「Seeding from: {最後の曲名} ほか2曲」のヒント行を Generate ボタン上に表示。チェックボックスで「シードを使わない」も選べるようにする（API はすでに `seed_track_ids` 省略可能）。
2. `presets.length === 0` のとき、Select の代わりに「Vibe プリセットがありません → Prompt Manager で作成」リンク（サイドバータブ切替コールバックを props で受ける）。
3. 生成結果の各行に前曲との関係バッジを表示: `±{bpm差}BPM` と キー相性（`utils/audio_math.py` の Camelot 隣接判定と同等のロジックを `src/components/setlist-creator/utils.ts` に実装。`SetlistEditor` でも再利用）。

---

## UX-07: WordTab（ワードプレイ）の待ち時間対策

**対象**: `src/components/setlist-creator/tabs/WordTab.tsx:66-87`

**現状**: 曲を選択するたびに歌詞取得 + LLM キーワード解析を直列で待つ（AI-08 参照）。歌詞表示まで全体がスピナーになる。

**改修内容**:
1. `getLyrics` と `analyzeLyrics` の表示を分離: 歌詞は取得でき次第すぐ描画し、キーワードは「Analyzing keywords…」のインラインスケルトンで後から差し込む。
```tsx
lyricsService.getLyrics(id).then(...);      // 即表示
lyricsService.analyzeLyrics(id).then(...);  // 後から keywords 反映
```
2. AI-08 のサーバーキャッシュ導入後は2回目以降が即時になる。キャッシュ済みかどうかをレスポンスの `cached: true` で受け、未キャッシュ時のみ「初回解析には時間がかかります」注記を表示。
3. 歌詞が無い曲を選択した場合、現在は 404 が console に出るだけ。「歌詞がありません → Tag Manager で Auto-Fill」の empty state を表示する。

---

## UX-08: ジャンル一括解析の結果サマリーとエラー詳細

**対象**: `src/components/genre-manager/`（AnalyzeAllTab / AnalyzeMissingTab）、`backend/app/services/genre_background_service.py`

**現状**: 進捗 WebSocket は `processed / errors` の数値のみ。どの曲が失敗したか、何がどう変わったかは完了後に確認できない。

**改修内容**:
1. `genre_background_service` の state に `recent_results: List[{track_id, title, old_genre, new_genre}]`（末尾50件のリングバッファ）と `failed_tracks: List[{track_id, title, error}]` を追加して broadcast。
2. フロントの解析モーダルに「変更ログ」リスト（old → new をライブ表示）と、完了時の「失敗 N 件を再試行」ボタンを追加（failed の track_ids で再度 start_batch_analysis を叩くだけ）。
3. 完了トーストに「{updated} 件更新 / {skipped} 件スキップ / {errors} 件失敗」を表示。

---

## UX-09: M3U8 エクスポート時の欠損ファイル警告

**対象**: `src/components/setlist-creator/`（エクスポートボタン周辺）、`backend/api/routers/setlists.py:57-78`

**現状**: ファイルが移動済みでも黙ってエクスポートされ、Rekordbox 側で初めて読み込めないことに気づく。

**改修内容**（BUG-17 とセット）:
1. `GET /api/setlists/{id}/export/validate` を新設し `{missing: [{id, title, filepath}], total: n}` を返す。
2. フロントはエクスポート押下時にまず validate を呼び、欠損があれば確認ダイアログ「3曲のファイルが見つかりません。除外してエクスポートしますか？」を表示してから download URL を開く。

---

## UX-10: 検索デバウンスとフィルタ操作の応答性

**対象**: `src/components/music-library/useTrackSearch.ts:51-54`

**現状**: クエリ・フィルタ・extraParams のどれが変わっても一律 300ms デバウンスで全リセット検索。フィルタ適用ボタン押下時にも 300ms 待つ。また `clearAllFilters` でクエリとフィルタを同時に変えると2回検索が走る。

**改修内容**:
1. デバウンスはテキスト入力 (`query`, `filters.lyrics`) のみに適用し、`applyFilters` / `clearAllFilters` は即時 `search(true)` を呼ぶ。
2. BUG-08 の世代管理（requestSeq）を入れた上で、入力中は前リクエストを破棄。
3. vibe 検索（LLM 解決）はデバウンス対象から外し、明示的な Apply ボタンでのみ発火させる（UX-02 の resolve フロー）。

---

## UX-11: FilterDialog のリセット・プリセット挙動の明確化

**対象**: `src/components/music-library/FilterDialog.tsx`、`MusicLibrary.tsx:56-78` (`clearFilter`)

**現状**:
- `clearFilter` がキー名の文字列 `includes("Energy")` 判定で min/max を同時クリアする等、対応漏れが起きやすい構造（`subgenres` バッジ、Danceability バッジは表示すら無い）。
- アクティブフィルタのバッジ表示が `bpm / key / Energy / Brightness` のみで、`genres / subgenres / year / duration / danceability / lyrics` は適用中でも見えない。

**改修内容**:
1. バッジ表示をフィルタ定義駆動にリファクタ:
```typescript
const FILTER_BADGES: { key: string; label: (f: FilterState) => string | null; clear: (f: FilterState) => FilterState }[] = [...]
```
   全フィルタ項目分を定義し、`label()` が null 以外を返すものだけバッジ描画。クリアも定義側の `clear()` を呼ぶ。
2. これにより「何が効いているかわからないまま絞り込まれている」状態を解消する。

---

## UX-12: 設定画面の LLM 接続テストの強化

**対象**: `src/components/settings-view/SettingsView.tsx`、`backend/api/routers/settings.py`

**現状**: `check_llm_status`（`backend/utils/llm.py:300-341`）は API キーの**存在確認のみ**で、キーが間違っていても "Configured" と表示される。実際のエラーは初回のジャンル解析等で初めて発覚する。

**改修内容**: AI-10 と同一。`POST /api/settings/llm-test` で実際に `generate_text(session, "Reply with OK")` を実行し、成否・レイテンシ・エラーボディを返す。Settings 画面に「Test Connection」ボタンと結果表示（成功: 緑バッジ + 応答時間 / 失敗: エラー詳細とドキュメントリンク）を追加。

---

## UX-13: グローバル進捗インジケーターの多重タスク対応

**対象**: `src/components/GlobalProgressIndicator.tsx`、`backend/app/services/background_task_service.py`

**現状**: ingestion / metadata / genre の3種のバックグラウンドタスクがそれぞれ独立した WebSocket とサービスインスタンスを持つ。`start_task` は実行中なら `False` を返すだけで、フロントに「既に別のタスクが実行中」という説明が出ない（API レスポンスの扱いを確認し、`{started: false}` 時のトーストを必ず出すこと）。

**改修内容**:
1. 各 start 系 API のレスポンスを `{started: bool, reason?: "already_running"}` に統一し、フロントで「既にジャンル解析が実行中です」をトースト表示。
2. `GlobalProgressIndicator` で複数タスクを縦に積んで表示できるようにする（現状実装を確認し、単一表示前提なら配列化する）。

---

## 改修優先度まとめ

| ID | 内容 | 優先度 | 備考 |
|----|------|--------|------|
| UX-01 | トースト基盤 + ApiError | **P0** | 他の多くの項目の前提 |
| UX-02 | Vibe 検索の可視化 | P1 | BUG-07 と同時実施 |
| UX-04 | 解析ボタンのフィードバック | P1 | BUG-13 と同時実施 |
| UX-05 | セットリスト保存状態/Undo | P1 | BUG-11 と同時実施 |
| UX-07 | WordTab 待ち時間 | P1 | AI-08 と同時実施 |
| UX-03 | 総件数表示 | P2 | |
| UX-06 | AutoTab 説明 | P2 | |
| UX-08 | ジャンル解析ログ | P2 | |
| UX-10 | デバウンス最適化 | P2 | BUG-08 と同時実施 |
| UX-09 | M3U8 欠損警告 | P3 | |
| UX-11 | フィルタバッジ網羅 | P3 | |
| UX-12 | LLM 接続テスト | P3 | AI-10 と同時実施 |
| UX-13 | 多重タスク表示 | P3 | |
