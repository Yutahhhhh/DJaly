# 02. AI 返答精度・LLM 連携の改善一覧

対象範囲: `backend/utils/llm.py`、`backend/app/services/genre_app_service.py`、`genre_background_service.py`、`setlist_app_service.py`、`backend/api/routers/lyrics.py`

ジャンル推定 / Vibe 検索 / セットリスト自動生成 / ワードプレイ抽出の4機能すべてが `generate_text()` 経由のフリーテキスト生成に依存しており、**構造化出力の強制・温度設定・コンテキスト投入・キャッシュ**の4点に大きな改善余地がある。

---

## AI-01: 全プロバイダーで JSON 構造化出力を強制する【最重要】

**対象**: `backend/utils/llm.py` の `_call_openai` / `_call_google` / `_call_anthropic` / `_call_ollama`

**現状**: 「JSON ONLY」とプロンプトで頼んでいるだけで、API レベルの JSON モードを一切使っていない。そのため:
- markdown フェンス除去 (`_clean_json_string`)、`find("{")`/`rfind("}")` での切り出しなど、呼び出し側に脆い後処理が散在
- Ollama の小型モデル (llama3.2) では JSON が崩れて解析失敗が頻発しうる

**改修内容**: `generate_text` に `json_mode: bool = False` 引数を追加し、各プロバイダーで構造化出力を有効化する。

```python
def generate_text(session, prompt, model_name=None, json_mode=False, json_schema=None) -> str:
```

| プロバイダー | 実装 |
|---|---|
| OpenAI | `"response_format": {"type": "json_object"}`（schema があれば `json_schema` タイプ） |
| Google Gemini | `generationConfig.response_mime_type = "application/json"`、schema があれば `responseSchema` も設定 |
| Anthropic | system プロンプトに schema を明記 + assistant の先頭に `{` をプリフィル（`messages` に `{"role": "assistant", "content": "{"}` を追加し、返答の先頭に `{` を補完） |
| Ollama | `client.generate(model=..., prompt=..., format="json")`（schema 指定可能な新形式 `format=schema_dict` にも対応） |

呼び出し側（`generate_vibe_parameters`、`analyze_track_with_llm`、`lyrics.py analyze_lyrics`）はすべて `json_mode=True` に切り替える。`_clean_json_string` はフォールバックとして残してよい。

**期待効果**: パース失敗による「解析失敗・空結果」が大幅減。特に Ollama 利用時の安定性向上。

---

## AI-02: タスク別に temperature を最適化する

**対象**: `backend/utils/llm.py`（現在は全プロバイダー一律 `temperature: 0.5`）

**現状**: 分類タスク（ジャンル推定）もパラメータ推定（vibe）も創作ではないのに 0.5 で揺らぎが入る。同じ曲を2回解析すると違うジャンルが返る一因。

**改修内容**: `generate_text` に `temperature: float = 0.2` 引数を追加し、用途別に指定する。

| 用途 | 推奨値 |
|---|---|
| ジャンル/サブジャンル推定 (`genre_app_service`) | **0.0** |
| Vibe パラメータ推定 (`generate_vibe_parameters`) | **0.1** |
| ワードプレイキーワード抽出 (`lyrics.py`) | 0.3（多様性が少し欲しい） |

**検証**: 同一トラックを5回解析してジャンルが一致する率（再現率）をテストで確認。

---

## AI-03: ジャンル推定プロンプトにライブラリの既存語彙を注入する

**対象**: `backend/app/services/genre_app_service.py` (`analyze_track_with_llm` / `analyze_tracks_batch_with_llm`)

**現状**: `DJ_GENRE_GUIDE` は「固定リストに縛られるな」と指示しており、LLM が毎回自由な表記を生成する。その結果 "Hip-Hop" / "Hip Hop" / "Rap" のような表記揺れが発生し、それを後段の Cleanup タブと `GENRE_ALIASES`（わずか16件のハードコード辞書）で吸収する自転車操業になっている。

**改修内容**: プロンプトに**そのユーザーのライブラリに既に存在するジャンル一覧**を提示し、「既存ラベルに合致するならそれを再利用、本当に無い場合のみ新規ラベル」と指示する。

```python
existing_genres = self.repository.get_all_genres()        # 既存メソッド
existing_subgenres = self.repository.get_all_subgenres()

prompt = f"""
...
Existing genres in this library (REUSE these labels when applicable,
including exact spelling/casing):
{", ".join(existing_genres[:60])}

Existing subgenres:
{", ".join(existing_subgenres[:80])}

Only introduce a new label when none of the existing ones fits.
- Genre labels must be in English.
"""
```

ポイント:
- 件数が多い場合は上位 N 件（トラック数順）に制限。`get_all_genres` をトラック数降順で返すよう拡張するとよい。
- 「Genre labels must be in English」を明記（日本語曲のタイトルから日本語ラベルが返って混在するのを防ぐ）。
- 返却後の `_normalize_genre_label` で、既存ジャンルとの **case-insensitive 一致**を最優先で適用する（`GENRE_ALIASES` より前に）。

**期待効果**: 表記揺れの発生源を断つ。Cleanup タブの作業量が激減する。

---

## AI-04: ジャンル推定に使うコンテキスト情報を増やす

**対象**: `genre_app_service.py` の両解析メソッド

**現状**: LLM に渡しているのは `Title / Artist / BPM` のみ。DB には `album`、`year`、`energy`、`danceability`、`subgenre`（片方解析時）、既存 `genre` があるのに使っていない。

**改修内容**: プロンプトの曲情報を拡張する。

```python
# 単曲解析
Track: {track.title} / {track.artist}
Album: {track.album or "Unknown"}
Year: {track.year or "Unknown"}
BPM: {bpm_str}
Audio features: energy={track.energy:.2f}, danceability={track.danceability:.2f}, brightness={track.brightness:.2f}
Current genre (may be wrong): {track.genre or "None"}
```

バッチ解析の行フォーマットも `ID|Title|Artist|BPM|Year|Album` に拡張（プロンプト冒頭の `Input:` 説明も合わせて更新）。

**注意**: アルバム名はリミックス集等でノイズになる場合があるので「Album はヒントであり決定打にしない」旨を Rules に追加する。

---

## AI-05: バックグラウンド一括ジャンル解析をチャンクバッチ化する

**対象**: `backend/app/services/genre_background_service.py:41-88`

**現状**: 1曲ごとに `analyze_track_with_llm`（=LLM 1コール）を直列実行。1000曲なら1000コール。API コスト・時間とも非効率で、曲単位の判断のためラベルの一貫性も出にくい。**既に実装済みの `analyze_tracks_batch_with_llm`（複数曲を1コールで処理）が使われていない。**

**改修内容**:
```python
CHUNK_SIZE = 15  # 1コールあたりの曲数（Ollama 小型モデルなら 8 程度に）

for chunk_start in range(0, total, CHUNK_SIZE):
    if not self.is_running:
        break
    chunk = track_ids[chunk_start:chunk_start + CHUNK_SIZE]
    with Session(engine) as session:
        service = GenreAppService(session)
        try:
            results = await asyncio.to_thread(
                service.analyze_tracks_batch_with_llm, chunk, mode
            )
            self.state["updated"] += len(results)
        except Exception as e:
            self.state["errors"] += len(chunk)
        self.state["processed"] += len(chunk)
    await self.emit_state()
```
補足対応:
- `analyze_tracks_batch_with_llm` に `overwrite` 引数を追加（現状は単曲版にしかなく、バッチ版は genre が non-Unknown でも上書きしないロジックが暗黙）。
- 返答に含まれなかった ID は再試行キューに積み、チャンク末尾で1回だけリトライ。
- チャンクサイズは設定値 (`settings` テーブル `genre_batch_size`) で調整可能にする。

**期待効果**: LLM コール数が 1/15、処理時間も大幅短縮。同チャンク内でラベルの一貫性が上がる。

---

## AI-06: Vibe パラメータ推定プロンプトの強化（few-shot + スキーマ + 日本語対応）

**対象**: `backend/utils/llm.py:343-393` (`generate_vibe_parameters`)

**現状の問題**:
- few-shot 例が無く、スケール（0-1 か 0-100 か）が揺れる前提で後処理正規化している
- 日本語プロンプト（「夜のドライブ向けチル」等）への言及がない
- `genre` 的な語が来ても無視される（bpm/energy のみ推定）

**改修内容**:
```python
system_prompt = """
You are a professional music curator. Convert the user's vibe description
(possibly in Japanese) into target audio features.

Return ONLY this JSON (all numeric, no strings):
{"bpm": <int 60-200>, "energy": <float 0.0-1.0>, "danceability": <float 0.0-1.0>,
 "brightness": <float 0.0-1.0>, "noisiness": <float 0.0-1.0>,
 "year_min": <int or omit>, "year_max": <int or omit>}

Examples:
- "peak time techno" -> {"bpm": 132, "energy": 0.92, "danceability": 0.85, "brightness": 0.6, "noisiness": 0.55}
- "夜のドライブ用チルR&B" -> {"bpm": 92, "energy": 0.35, "danceability": 0.6, "brightness": 0.35, "noisiness": 0.2}
- "90s hip hop classics" -> {"bpm": 94, "energy": 0.6, "danceability": 0.75, "brightness": 0.45, "noisiness": 0.4, "year_min": 1990, "year_max": 1999}
"""
```
- AI-01 の `json_mode=True` で呼ぶ。
- BUG-04 の Pydantic 検証 (`VibeParams`) とセットで導入する。
- 戻り値に `genre_hints: List[str]` を追加し（スキーマに含める）、`fetch_candidates_pool` のジャンルフィルタ未指定時の優先ソートに使う拡張も検討（第2段階でよい）。

---

## AI-07: Vibe 解釈結果のキャッシュと再利用

**対象**: `backend/utils/llm.py`、`backend/app/services/track_app_service.py`、`setlist_app_service.py`

**現状**: 同じプリセット・同じプロンプトでも毎回 LLM を呼ぶ。`recommend_next_track` は曲を1つ進めるたびに preset の vibe を再推定する。

**改修内容**:
1. モジュールレベルの TTL キャッシュを導入:
```python
from cachetools import TTLCache
_vibe_cache: TTLCache = TTLCache(maxsize=256, ttl=600)

def generate_vibe_parameters(prompt_text, model_name=None, session=None):
    cache_key = (prompt_text.strip(), model_name or "")
    if cache_key in _vibe_cache:
        return dict(_vibe_cache[cache_key])
    ...
    _vibe_cache[cache_key] = dict(params)
```
2. プリセット由来の vibe は preset 保存時に解決して `presets` テーブルに `resolved_params_json` として永続化し、生成時は LLM を呼ばない選択肢も検討（プロンプト変更時に無効化）。

**注意**: BUG-07（ページネーションごとの再実行）の根本対策と同一基盤。`cachetools` は `backend` の依存に追加が必要（`pyproject.toml` / `requirements`を確認して追記）。

---

## AI-08: ワードプレイキーワード抽出の永続キャッシュと品質向上

**対象**: `backend/api/routers/lyrics.py:30-97` (`analyze_lyrics`)、`src/components/setlist-creator/tabs/WordTab.tsx`

**現状の問題**:
- WordTab で曲を選択するたびに LLM 解析 + **全曲の歌詞を全件メモリロードして部分一致カウント**を毎回実行。曲を切り替えるだけで数秒〜数十秒待たされる
- 抽出結果はどこにも保存されない
- 歌詞先頭 2000 文字しか見ていない（LRC タイムタグ込みだと実質歌詞 1 コーラス分程度）

**改修内容**:
1. `lyrics` テーブルに `keywords_json TEXT` と `keywords_content_hash TEXT` カラムを追加（`infra/database/schema.py` のマイグレーションに追記）。
2. `analyze_lyrics` は `sha256(content)` が `keywords_content_hash` と一致すればキャッシュを返す。不一致時のみ LLM 実行し保存。
3. LLM に渡す前に LRC タイムタグを除去してから 3000 文字に拡大:
```python
clean_content = re.sub(r'\[\d{1,2}:\d{2}(?:\.\d+)?\]', '', lyrics_obj.content)[:3000]
```
4. 全曲カウントは SQL に置き換え:
```sql
SELECT count(*) FROM lyrics WHERE track_id != :tid AND content ILIKE :kw
```
   キーワード数×1クエリで十分高速（DuckDB）。さらに `force: bool = False` クエリパラメータで再解析を許可。

**期待効果**: 2回目以降の WordTab 表示が即時化。LLM コスト削減。

---

## AI-09: LLM エラーのリトライとレート制限対応

**対象**: `backend/utils/llm.py` (`_execute_request`)

**現状**: HTTP 429 / 503 / タイムアウトでも即座に `API_ERROR:` 文字列を返して終了。バッチ解析中に1回の 429 で当該曲がエラー扱いになる。

**改修内容**: `_execute_request` に指数バックオフを実装。
```python
RETRYABLE = {429, 500, 502, 503, 529}
for attempt in range(3):
    try:
        ...
    except urllib.error.HTTPError as e:
        if e.code in RETRYABLE and attempt < 2:
            time.sleep(2 ** attempt * 2)  # 2s, 4s
            continue
        ...
```
Gemini の `BLOCKED:` 返答時は、ジャンル解析に限り**メタデータだけで再試行**（歌詞や曲名の一部がセーフティに触れるケースの回避）するフォールバックを `genre_app_service` 側に追加。

---

## AI-10: デフォルトモデル名の更新と起動時検証

**対象**: `backend/utils/llm.py:39-49` (`get_llm_config`)

**現状**: Google のデフォルトが `gemini-1.5-flash`（既に提供終了/非推奨系列）。古いモデル名のまま API に投げると 404 が返り、ユーザーには `API_ERROR: 404` しか見えない。

**改修内容**:
1. デフォルトを現行世代に更新（例: `gemini-2.0-flash` 以降。実装時点の Google AI ドキュメントで現行の flash 系列を確認して指定すること）。Anthropic / OpenAI のデフォルトも同様に現行モデルを確認。
2. `check_llm_status`（settings 画面の接続テスト）を拡張し、実際に 1 トークン程度の生成を行う「実打鍵テスト」ボタンを設ける（`/api/settings/llm-test` 新設）。エラー時は API のエラーボディをそのまま表示する。
3. モデル名はプロバイダーごとに `settings` テーブルへ分離保存（`llm_model_google`, `llm_model_openai`...）し、プロバイダー切替時に前のモデル名が残って 404 になる事故を防ぐ。

---

## AI-11: セットリスト生成アルゴリズムへの vibe 反映を強化

**対象**: `backend/domain/services/setlist_builder.py` (`build_chain`)

**現状**: `build_chain` の vibe スコアは `energy` の差分 × 0.1 のみ。`generate_vibe_parameters` が返す `danceability` / `brightness` / `year_min/max` は**プール絞り込み（SQL）にしか使われず、曲順決定に反映されない**。また、セット全体のエネルギーカーブ（徐々に上げる等）の概念がない。

**改修内容**（段階導入可）:
1. 遷移スコアに danceability / brightness の近接度も加味:
```python
for feat in ("energy", "danceability", "brightness"):
    if feat in vibe_params:
        vibe_score -= abs(getattr(candidate["track"], feat) - vibe_params[feat]) * 0.1
```
2. プリセットに `energy_curve: "flat" | "build" | "peak_and_release"` を追加し、`build_chain` 内で位置 `len(chain)/target_length` に応じた目標 energy を線形補間して評価する（Bridge モードの `build_path` と同じ発想を Infinite に持ち込む）。
3. 同一アーティスト連続を減点（`-0.2` 程度）して単調さを防ぐ。

---

## AI-12: recommend_next_track の vibe コンテキスト改善

**対象**: `backend/app/services/setlist_app_service.py:119-178`

**現状**: preset 指定時のコンテキストが `f"Reference: {target_track.title}. Goal: {prompt.content}"` のみで、現在の曲の BPM・キー・energy を LLM に渡していない。また LLM 失敗時 (`{}`) は黙って vibe 無しにフォールバックする。

**改修内容**:
```python
ctx = (
    f"Current track: {target_track.title} by {target_track.artist} "
    f"(BPM {target_track.bpm:.0f}, key {target_track.key}, energy {target_track.energy:.2f}). "
    f"Set goal: {prompt.content}. "
    f"Estimate features for the NEXT track to play."
)
```
AI-07 のキャッシュキーには track_id も含める（曲ごとに文脈が変わるため TTL は短め or preset 単位キャッシュに切替）。

---

## 実装順序の推奨

1. **AI-01 + AI-02 + BUG-04**（構造化出力・温度・検証）— すべての精度問題の土台
2. **AI-07 + BUG-07**（vibe キャッシュ）— 体感速度とコストに直結
3. **AI-03 + AI-04 + BUG-10**（ジャンル語彙注入・コンテキスト拡充・verified 条件）
4. **AI-05**（バッチ化）
5. **AI-08**（ワードプレイキャッシュ）
6. AI-09 / AI-10 / AI-11 / AI-12
