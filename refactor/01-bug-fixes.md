# 01. 潜在バグ改修一覧

実コードを精査して特定した、再現性の高い順のバグリスト。各項目に「対象ファイル / 現状 / 問題 / 改修内容 / 検証方法」を記載。

> **実装状況 (2026-06-12)**: BUG-01〜17 すべて実装済み。テストは `backend/tests/test_refactor_fixes.py` に追加 (109 passed)。
> 実装中に新たに **BUG-18 / BUG-19** を発見し、これらも修正済み (本ドキュメント末尾参照)。

---

## BUG-01: 類似曲サジェストの similarity 値が誤った曲のスコアを表示している【High】

**対象**: `backend/app/services/recommendation_app_service.py:153-160` (`get_suggestions_for_track`)

**現状**:
```python
matched_sims = similarities[matched_indices]
sorted_indices = matched_indices[np.argsort(matched_sims)[::-1]]
top_indices = sorted_indices[:50]
...
for i, idx in enumerate(top_indices):
    cid = candidate_ids[idx]
    if cid in track_map:
        suggestions.append(TrackSuggestion(
            track=track_map[cid],
            similarity=float(matched_sims[i])   # ← バグ
        ))
```

**問題**: `matched_sims` は**ソート前**の配列なのに、ソート後の列挙位置 `i` でアクセスしている。返却される `similarity` は別の曲の類似度。UI 上の類似度表示・閾値判断がすべて狂う。

**改修内容**: 全候補に対する `similarities[idx]` を使う。
```python
for idx in top_indices:
    cid = candidate_ids[idx]
    if cid in track_map:
        suggestions.append(TrackSuggestion(
            track=track_map[cid],
            similarity=float(similarities[idx])
        ))
```

**検証**: `backend/tests/` に、埋め込みベクトルを3件投入し、返却順と similarity が降順かつ正しいペアであることを assert するテストを追加。

---

## BUG-02: ワードプレイ削除 API が常に 422 で失敗する【High】

**対象**:
- `backend/api/routers/setlists.py:131-147` (`update_setlist_track_wordplay`)
- `src/services/setlists.ts:56-60` (`deleteWordplay`)

**現状**: フロントは削除時に `wordplay_json: null` を PATCH するが、バックエンドは
```python
wordplay_json: str = Body(..., embed=True)
```
と **required な str** で受けているため、`null` は Pydantic バリデーションで 422 になる。`SetlistCreator.tsx` の `handleDeleteWordplay` は catch して console.error するだけなので、ユーザーには「削除ボタンを押しても消えない」ように見える。

**改修内容**: バックエンドを Optional に変更。
```python
@router.patch("/api/setlist-tracks/{setlist_track_id}/wordplay")
def update_setlist_track_wordplay(
    setlist_track_id: int,
    wordplay_json: Optional[str] = Body(None, embed=True),
    session: Session = Depends(get_session)
):
```
`track.wordplay_json = wordplay_json`（None なら削除扱い）。

**検証**: `wordplay_json: null` の PATCH が 200 を返し、DB 上の値が NULL になること。UI でワードプレイカードの × ボタン → カードが消えること。

---

## BUG-03: セットリスト自動生成系 API で subgenres フィルタが無視される【High】

**対象**:
- `src/services/setlists.ts` (`recommendNext` / `generateAuto` / `generatePath` は `subgenres` を送信)
- `backend/api/routers/setlists.py` (3エンドポイントとも `subgenres` パラメータが存在しない)
- `backend/app/services/setlist_app_service.py` / `backend/infra/repositories/recommendation_repository.py`

**現状**: `AutoTab.tsx` で「Filter Subgenres」を選択しても、FastAPI 側に受け口がないため**黙って無視**される。ユーザーから見るとサブジャンル絞り込みが効かない。

**改修内容**:
1. 3つのルーターに `subgenres: Optional[List[str]]` を追加し、サービス層へ伝搬。
2. `fetch_candidates_pool` のシグネチャに `subgenres` を追加し、SQL 条件を分離:
```sql
-- genres 指定時:    AND t.genre IN :genres
-- subgenres 指定時: AND t.subgenre IN :subgenres
```
※ 現在は `genres` が genre/subgenre 両カラムに OR マッチしている（`recommendation_repository.py:114`）。genre と subgenre を別条件に分けることで Music Library 検索 (`track_repository._apply_search_conditions` の挙動) と一貫させる。

**検証**: subgenres のみ指定して `/api/recommendations/auto` を叩き、結果が該当サブジャンルのみになること。

---

## BUG-04: LLM が返す vibe パラメータが未検証のまま SQL に直接埋め込まれている（クラッシュ + SQLインジェクション経路）【High】

**対象**:
- `backend/utils/llm.py:343-393` (`generate_vibe_parameters`)
- `backend/infra/repositories/recommendation_repository.py:117-138` (`fetch_candidates_pool`)
- `backend/infra/repositories/track_repository.py:137-155` (`_apply_search_conditions`)

**現状の問題点（複合）**:
1. `generate_vibe_parameters` は LLM の JSON をほぼそのまま返す。`bpm` が `"120"`（文字列）や `null` で返ると:
   - `fetch_candidates_pool` の `vibe_params["bpm"] > 0` が `TypeError` → 500 エラー
   - `_apply_search_conditions` の `int(target_params["year_min"])` が `ValueError`/`TypeError` → 500 エラー
2. `recommendation_repository.py:128,131` で値を **f-string で SQL に直接連結**:
   ```python
   order_clauses.append(f"ABS(t.energy - {vibe_params['energy']})")
   ```
   LLM 出力が文字列の場合、任意 SQL 片が ORDER BY に入る（ローカルアプリだが LLM 出力起点のインジェクション経路）。
3. `llm.py:369` の `end = response_text.rfind("}") + 1` は `rfind` 失敗時に `0` になるが、判定が `if start != -1 and end != -1:` のため、`}` が無いケースを検出できない（`end != 0` が正しい）。

**改修内容**:
1. `generate_vibe_parameters` の戻り値を Pydantic で厳格に検証・型変換・クランプする:
```python
from pydantic import BaseModel, field_validator

class VibeParams(BaseModel):
    bpm: Optional[float] = None          # 60-200 にクランプ
    energy: Optional[float] = None       # 0.0-1.0
    danceability: Optional[float] = None
    brightness: Optional[float] = None
    noisiness: Optional[float] = None
    year_min: Optional[int] = None       # 1900-2100
    year_max: Optional[int] = None
```
   変換不能な値は**そのキーを破棄**して続行（全体を失敗させない）。返却は `params.model_dump(exclude_none=True)`。
2. ORDER BY をプレースホルダ化:
```python
order_clauses.append("ABS(t.energy - :order_energy)")
params["order_energy"] = float(vibe_params["energy"])
```
3. `end` 判定を `if start != -1 and end > start:` に修正。

**検証**: LLM モックが `{"bpm": "fast", "energy": "0.9", "year_min": null}` を返すテストで、500 にならず energy=0.9 だけが適用されること。

---

## BUG-05: ベクトル類似検索 SQL の文字列連結と次元数 200 のハードコード【Medium】

**対象**: `backend/infra/repositories/track_repository.py:82-89` (`get_similar_tracks`)

**現状**:
```python
.order_by(text(f"array_cosine_similarity(CAST(track_embeddings.embedding_json AS FLOAT[200]), CAST('{vec_str}' AS FLOAT[200])) DESC"))
```

**問題**:
1. `vec_str`（DB 由来 JSON）を SQL に直接連結。JSON が壊れている場合に SQL エラー。
2. 埋め込み次元 `200` がハードコード。解析パイプラインの次元が変わると全クエリが壊れる。`backend/domain/services/analysis/constants.py` 等に `EMBEDDING_DIM` 定数を作り共有する。

**改修内容**: バインドパラメータ化 + 定数化。
```python
from sqlalchemy import bindparam
sim = text(
    f"array_cosine_similarity(CAST(track_embeddings.embedding_json AS FLOAT[{EMBEDDING_DIM}]), "
    f"CAST(:target_vec AS FLOAT[{EMBEDDING_DIM}])) DESC"
).bindparams(bindparam("target_vec", value=vec_str))
```

---

## BUG-06: メタデータ自動取得のスキップキャッシュ誤登録【Medium】

**対象**: `backend/app/services/metadata_app_service.py:183-201` (`_update_release_date`)、`:93-98`（スキップキャッシュ適用条件）

**現状の問題点（2件）**:
1. iTunes でリリース日が**見つかったのに既に同じ年だった**場合、`return False, "not_found"` に落ちて **skip cache に「見つからない曲」として永久登録**される。以後 overwrite なしでは再取得対象から外れる。
2. キャッシュ除外条件 `if track_ids is None or not overwrite:` により、「全曲 + Overwrite ON」で実行してもキャッシュ済みの曲はスキップされる。overwrite はキャッシュを無視すべき。

**改修内容**:
```python
# 1. 見つかったが変更なしのケースを分離
if release_date:
    try:
        year = int(release_date[:4])
    except (ValueError, TypeError):
        return False, "not_found"
    if track.year == year:
        return False, "already_exists"   # ← not_found にしない
    track.year = year
    session.commit()
    return True, None
return False, "not_found"

# 2. キャッシュ適用条件
if not overwrite:
    skip_ids = self._skip_cache.get(update_type, set())
    ...
```

**検証**: 同年データの曲を2回処理しても skip cache JSON に track_id が入らないこと。overwrite=True で skip cache 対象曲も処理されること。

---

## BUG-07: Vibe 検索がページネーションごとに LLM を再実行し、結果の整合性が壊れる【High】

**対象**:
- `backend/app/services/track_app_service.py:50-53, 112-115`
- `src/components/music-library/useTrackSearch.ts`（無限スクロールで offset を変えて同条件再リクエスト）

**現状**: `vibe_prompt` 付き `/api/tracks` はリクエストごとに `generate_vibe_parameters`（LLM 呼び出し、最大60秒）を実行。無限スクロールで2ページ目を読むたびに:
1. **毎ページ LLM コスト・レイテンシが発生**
2. LLM は非決定的なので 1ページ目と2ページ目で **ORDER BY 基準が変わり、曲の重複・欠落**が起きる
3. `get_track_ids`（全件選択用）でも**再度** LLM が呼ばれ、リスト表示と ID リストが食い違う

**改修内容**（推奨案: サーバー側キャッシュ）:
1. `utils/llm.py` に `functools.lru_cache` 相当のキャッシュを追加（プロンプト文字列 + provider + model をキー、TTL 10分程度。`cachetools.TTLCache` か自前 dict + timestamp）。
2. もしくは API を2段階に分離: `POST /api/vibe/resolve` で `{prompt} -> {params}` を一度だけ取得し、フロントは解決済みパラメータ (`min_energy` 等) で `/api/tracks` を呼ぶ。**こちらの方が UI に「AI解釈結果」を表示できるため UX 的にも優位**（→ 03-usability.md UX-03 参照）。

**検証**: 同一 vibe_prompt で offset=0,50 を連続リクエストし、LLM 呼び出しが1回のみ・2ページに重複 ID がないこと。

---

## BUG-08: useTrackSearch の競合状態（古いレスポンスが新しい結果を上書き）【Medium】

**対象**: `src/components/music-library/useTrackSearch.ts`

**現状**: `search` に AbortController も世代管理もない。タイプ中に 300ms デバウンスで連続発火した場合、遅い旧リクエスト（特に vibe 検索の LLM 待ち）が後着して新しい結果を上書きする。また `useCallback` の依存に `search` 自体が `useEffect` 依存から漏れており（`eslint-disable` 状態）、古いクロージャ実行のリスクがある。

**改修内容**:
```typescript
const requestSeq = useRef(0);

const search = useCallback(async (resetPage = false) => {
  const seq = ++requestSeq.current;
  setLoading(true);
  try {
    ...
    const data = await tracksService.getTracks(finalParams);
    if (seq !== requestSeq.current) return; // 古いレスポンスは破棄
    ...
  } finally {
    if (seq === requestSeq.current) setLoading(false);
  }
}, [query, filters, limit, page, extraParamsKey]);
```
あわせて `extraParams` は `JSON.stringify` を変数 (`extraParamsKey`) に切り出して依存配列を統一する。

**検証**: ネットワークスロットリング下で高速にクエリを変更し、最終表示が最後のクエリ結果と一致すること。

---

## BUG-09: バックエンド起動時にポート使用中プロセスを無差別 kill -9【Medium】

**対象**: `backend/server.py:39-57`

**現状**: `lsof -t -i:PORT` の結果を**プロセス名を確認せず** `kill -9`。ユーザーが偶然同じポートを使う他アプリ（開発サーバー等）を強制終了させる恐れがある。また起動メッセージの print が2回重複している（34行目と59行目）。

**改修内容**:
```python
result = subprocess.run(["lsof", "-t", f"-i:{port}"], capture_output=True, text=True)
for pid in result.stdout.strip().split("\n"):
    if not pid or pid == str(os.getpid()):
        continue
    # プロセス名を確認し、自分自身のサイドカー/Pythonのみ kill
    name = subprocess.run(["ps", "-p", pid, "-o", "comm="], capture_output=True, text=True).stdout.strip()
    if any(k in name.lower() for k in ("djaly", "python", "server")):
        subprocess.run(["kill", pid])  # まず SIGTERM
```
重複 print は1つ削除。

---

## BUG-10: ジャンル解析失敗・"Unknown" 返答でも is_genre_verified=True になり、未解析リストから消える【Medium】

**対象**: `backend/app/services/genre_app_service.py`
- `analyze_track_with_llm` (162-165行): `should_update` が True なら無条件で `is_genre_verified = True`
- `analyze_tracks_batch_with_llm` (287行): LLM 行がパースできた曲は **変更が無くても** `is_genre_verified = True`

**問題**: LLM が `Unknown` を返した曲・confidence が Low の曲も「検証済み」になり、`get_unknown_tracks`（`is_genre_verified == False` ベース）の対象から外れる。再解析の導線が事実上消える。さらに検証済みトラックはレコメンドの教師ベクトル (`get_verified_tracks_with_embeddings`) に使われるため、誤ラベルが類似曲ジャンル推定を汚染する。

**改修内容**:
1. `genre` が `Unknown`/空のままなら `is_genre_verified` を立てない。
2. `confidence` が `Low` の場合も立てない（単発解析時）。
```python
applied_genre = (track.genre or "").strip().lower()
if applied_genre and applied_genre != "unknown" and response.confidence != "Low":
    track.is_genre_verified = True
```
3. バッチ側も `has_changes or (track.genre and track.genre.lower() != "unknown")` を条件にする。

**検証**: LLM モックで `{"genre": "Unknown"}` を返したとき、当該曲が `get_unknown_tracks` の結果に残ること。

---

## BUG-11: セットリスト保存が「全削除→再挿入」で、連続ドラッグ時に競合してトラック消失の恐れ【Medium】

**対象**:
- `backend/app/services/setlist_app_service.py:72-101` (`update_setlist_tracks`)
- `src/components/setlist-creator/SetlistCreator.tsx:68-115` (`commitTracksToDB`)

**現状**: 保存のたびに `clear_tracks` → 再 INSERT → commit ×2。フロントはドラッグ完了ごとに `commitTracksToDB` を await なしで多重発火し得る（`handleDragEnd` は同期）。2つの保存が交差すると「クリア(A) → クリア(B) → 挿入(A) → 挿入(B)」のような順序になり、重複や消失が起きうる。

**改修内容**:
1. バックエンド: clear と insert と updated_at 更新を**単一トランザクション**にまとめる（commit を1回に）。
2. フロント: 保存処理を直列化する。
```typescript
const saveQueue = useRef(Promise.resolve());
const commitTracksToDB = (newTracks) => {
  saveQueue.current = saveQueue.current.then(() => doCommit(newTracks));
  return saveQueue.current;
};
```
3. 保存失敗時に console.error だけでなくトースト表示（→ UX-01）。

---

## BUG-12: Bridge モードで END トラックがセットリストに挿入されない【Medium】

**対象**: `src/components/setlist-creator/tabs/AutoTab.tsx:137-163` (`handleApply`)

**現状**: `tracksToInject` が `endTrack.id` を常に除外しているため、END に**ライブラリからドラッグした（まだセットリストに無い）曲**を指定した場合、ブリッジ適用後も END 曲自体は追加されない。中間曲だけ入って終点が無いセットリストになる。

**改修内容**: END がセットリストに存在しない場合は除外しない。
```typescript
const endAlreadyInList = endTrack
  ? currentSetlistTracks.some((st) => st.id === endTrack.id)
  : false;
const tracksToInject = filteredAutoTracks.filter(
  (t) => t.id !== startTrack.id && (endAlreadyInList ? t.id !== endTrack!.id : true)
);
```

**検証**: START=セットリスト末尾曲、END=ライブラリ曲でブリッジ生成→Apply 後、最後に END 曲が入ること。

---

## BUG-13: 楽曲解析ボタンが解析完了前にリストを更新してしまう【Low】

**対象**: `src/components/music-library/MusicLibrary.tsx:80-93` (`handleAnalyze`)

**現状**: `ingestService.ingest()` はバックグラウンドタスクを起動するだけなのに、直後に `search(true)` を呼んでいる。解析完了前のデータで再描画されるため「ボタンを押しても何も変わらない」ように見える。

**改修内容**: `IngestionContext`（WebSocket 進捗）の完了イベントを購読して、`type === "complete"` 受信時に `search(true)` を呼ぶ。最低限の対応としては解析中バッジを表示し、完了通知までボタンを disabled に保つ。

---

## BUG-14: API クライアントがエラーレスポンスの detail を捨てている【Low】

**対象**: `src/services/api-client.ts`（全メソッド）

**現状**: `throw new Error(\`API Error: ${response.status} ${response.statusText}\`)`。FastAPI は `{"detail": "Track not found"}` 等を返すのに、UI には statusText しか出ない。LLM 設定不備 (`CONFIG_ERROR: API Key for google is not set.`) など**ユーザーが対処可能なエラー**が握りつぶされる。

**改修内容**:
```typescript
if (!response.ok) {
  let detail = response.statusText;
  try {
    const body = await response.json();
    if (body?.detail) detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
  } catch {}
  throw new ApiError(response.status, detail);
}
```
`ApiError` クラス（status と detail を保持）を新設し、呼び出し側のトースト表示（UX-01）で利用する。あわせて `AbortSignal.timeout(120_000)` を fetch に渡し、ハング対策とする（vibe 検索は LLM 待ちがあるため長め）。

---

## BUG-15: 歌詞検索のスニペット生成で正規表現が貪欲マッチし歌詞本文を削りすぎる【Low】

**対象**: `backend/api/routers/lyrics.py:124,129`、`src/components/setlist-creator/tabs/WordTab.tsx:55,126`

**現状**: `re.sub(r'\[.*\]', '', line)` / `line.replace(/\[.*\]/, "")` は貪欲マッチのため、`[00:01.00]I love [you] baby` のような行で `[` から最後の `]` までが全部消える。

**改修内容**: 非貪欲 + タイムタグ限定にする。
```python
re.sub(r'\[\d{1,2}:\d{2}(?:\.\d+)?\]', '', line)
```
```typescript
line.replace(/\[\d{1,2}:\d{2}(?:\.\d+)?\]/g, "")
```

---

## BUG-16: BackgroundTaskService.update_state のデッドコードと ETA 計算の競合【Low】

**対象**: `backend/app/services/background_task_service.py:101-124`

**現状**: `update_state` の末尾に意味のない `pass` と「broadcast すべきか」の長い思考コメントが残存。また `start_time` が `_task_wrapper` でセットされる前に `update_state` が ETA を計算すると `time.time() - 0` で巨大な ETA になる。

**改修内容**: コメント・`pass` を削除し、`if self.state["start_time"] > 0 and done > 0 and self.state["total"] > 0:` にガードを追加。

---

## BUG-17: M3U8 エクスポートにファイル存在チェックが無い【Low】

**対象**: `backend/app/services/setlist_app_service.py:103-117` (`export_as_m3u8`)

**現状**: 移動・削除済みのファイルパスもそのまま出力され、Rekordbox 側で黙って読み込み失敗する。

**改修内容**: `os.path.exists(track.filepath)` をチェックし、存在しない曲は `# MISSING: ...` コメント行として出力 + レスポンスヘッダーかレスポンス JSON（エンドポイント分離）で欠落件数を返してフロントで警告表示する（→ UX-09）。

---

## BUG-18: 類似曲ジャンルサジェスト API がヒット時に常に 500 になっていた【High・実装中に発見】

**対象**: `backend/app/services/recommendation_app_service.py` (`get_suggestions_for_track`)、`backend/api/schemas/genres.py`

**現状**: `TrackSuggestion(track=..., similarity=...)` と構築していたが、スキーマは flat 形式 (`id/title/artist/bpm/filepath`、必須) のため、**候補が1件でもヒットすると Pydantic ValidationError → 500**。フロント (`src/services/genres.ts`) も flat 形式を期待している。`GET /api/genres/grouped-suggestions/{track_id}` は実質機能していなかった。

**改修内容(実装済み)**: flat 形式で構築するよう修正し、スキーマに `similarity: Optional[float]` を追加。BUG-01 の修正(正しい similarity 値)もここに統合。

---

## BUG-19: Tag Manager の「Full Library Analysis」が常に 404【High・実装中に発見】

**対象**: `src/components/genre-manager/AnalyzeAllTab.tsx`、`backend/api/routers/genres.py`

**現状**: フロントは `POST /api/genres/analyze-all` を呼ぶが、**バックエンドにこのエンドポイントが存在しない**ため常に 404。さらに進捗表示がファイル解析用の `useIngestion`(別 WebSocket)を購読しており、仮に動いても進捗が出ない。`genre_background_service` と `/ws/genres/analysis` はフロントから一切使われていなかった。

**改修内容(実装済み)**:
1. `POST /api/genres/analyze-all` を新設 (mode=keep: 未検証曲のみ / overwrite: 全曲)。AI-05 のチャンクバッチで実行。
2. `src/components/genre-manager/useGenreAnalysis.ts` を新設し `/ws/genres/analysis` を購読。
3. `AnalyzeAllTab` を正しいソケットに接続し、進捗・キャンセル・変更ログ(old→new)・失敗再試行 UI を追加 (UX-08 を兼ねる)。

---

## 改修優先度まとめ

| ID | 内容 | 優先度 | 影響範囲 |
|----|------|--------|----------|
| BUG-02 | ワードプレイ削除 422 | High | 機能が完全に壊れている |
| BUG-03 | subgenres 無視 | High | フィルタが効かない |
| BUG-07 | Vibe検索の毎ページLLM実行 | High | 性能・整合性・コスト |
| BUG-01 | similarity 誤表示 | High | 表示値が誤り |
| BUG-04 | vibe パラメータ未検証 | High | 500エラー・SQL注入経路 |
| BUG-10 | Unknown でも verified | Medium | AI 精度の汚染源 |
| BUG-06 | skip cache 誤登録 | Medium | データ取得漏れ |
| BUG-08 | 検索レース | Medium | 表示不整合 |
| BUG-11 | セットリスト保存競合 | Medium | データ消失リスク |
| BUG-12 | Bridge END 欠落 | Medium | 機能不全 |
| BUG-09 | kill -9 | Medium | 他アプリ巻き添え |
| BUG-05 | SQL連結・次元固定 | Medium | 保守性・堅牢性 |
| BUG-13〜17 | その他 | Low | 体感品質 |
