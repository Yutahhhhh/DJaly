# ワードプレイの組み合わせ表

ワードプレイをセットリストとは独立して保存します。サイドバーの **Wordplay** で提案を確認し、承認・却下できます。

## 提案と承認

1. MCPの `search_tracks` で使用する音源のIDを確認します。同じ曲でも原曲・Remixは別IDで登録します。
2. `list_wordplay_pairs` で既存の組み合わせを確認します。必要に応じて `get_track_lyrics` / `find_wordplay_links` で接続語を調べます。前曲の展開末尾から次曲の展開先頭へ渡せる箇所を優先し、実際に登録された音源のBPM差を確認します。
3. `propose_wordplay_pairs` に候補をまとめて渡します。すべて `pending`（提案中）として登録されます。
4. Wordplay画面で曲・接続語・出典・確認状況を確認し、承認すると `approved` になります。MCPの `approve_wordplay_pair` はユーザーがその組を承認したときにだけ使います。
5. 却下は `reject_wordplay_pair` または画面の却下操作です。組み合わせのレコードを物理削除します。楽曲・音源ファイル・保存済みセットリストには影響しません。

```json
{
  "pairs": [
    {
      "from_track_id": 101,
      "to_track_id": 202,
      "keyword": "yeah",
      "source_phrase": "yeah",
      "target_phrase": "yeah",
      "source_section_position": "end",
      "target_section_position": "start",
      "from_timestamp": 62.5,
      "to_timestamp": 4.0,
      "transition_notes": "前曲の展開末尾を言い切り、次曲の展開頭へカットする。",
      "source_url": "",
      "evidence_type": "hypothesis",
      "verification_status": "unverified"
    }
  ]
}
```

IDは説明用です。実際のライブラリで取得したIDに置き換えます。1回1〜50件、同じ方向・同じ接続語の重複提案は既存内容を返し、承認やメモを上書きしません。A→BとB→Aは別の組み合わせです。

新しい候補の承認には、`source_section_position=end`、`target_section_position=start`、両方のCue時刻、実音源のBPM差2%以内が必要です。APIはBPM差を`bpm_delta_percent`、条件の合否を`boundary_fit`で返します。Cueは0秒以上、曲尺未満でなければ登録・更新できません。既存の承認済みデータは旧基準のまま維持されます。

## 承認と実音確認は別

- `status`: `pending` / `approved`
- `evidence_type`: `hypothesis`（接続案）/ `edit_listing`（Edit掲載）/ `performance`（実演資料）
- `verification_status`: `unverified` / `tested`（現在の音源で確認済み）
- `source_section_position` / `target_section_position`: `unknown` / `start` / `middle` / `end`

承認しても `tested` には変わりません。時刻の単位は秒、未確認はnullです。Editが商品として存在することと、所持している2曲で再現できることは別です。

## セットリストでの利用

承認済みのA→Bは、次曲推薦・自動生成・ブリッジ生成の評価に加点されます。強制接続ではなく、BPM・キー・音響特徴・全体の流れと合わせて評価します。ジャンル・年代などの候補条件は引き続き有効です。提案中の組は生成に使いません。

採用された接続語・Cue・元曲ID・組み合わせIDを `wordplay_json` に含めて返すので、セットリストに保存できます。MCPから結果を保存するときは `set_setlist_tracks(setlist_id=..., track_data=生成結果のtracks)` として渡すとWordplay情報も保持できます。従来どおり `track_ids` だけを渡すと接続情報は保存されません。

セットリスト作成画面のWordタブでは、選択した曲を起点とする承認済みの組み合わせを表示して追加できます。歌詞が未登録でも使えます。

却下した履歴は残りません。同じ案を将来あらためて提案すると新しい `pending` として登録されます。

## REST API

- `GET /api/wordplay-pairs`: status / from_track_id / query / limit / offsetで絞り込み、`{items,total}` を返します。
- `POST /api/wordplay-pairs`: 1件提案します。
- `POST /api/wordplay-pairs/{id}/approve`: 承認します。
- `DELETE /api/wordplay-pairs/{id}`: 組み合わせだけを削除します。
- `PATCH /api/wordplay-pairs/{id}`: メモ・出典・Cue・確認状態などを更新します。確認状態だけの変更は承認を維持します。内容変更は再承認待ちになり、曲・接続語・Cueの変更は実音確認状態も未確認に戻します。

既存CSVの100組やrekordboxのプレイリストは自動登録しません。Djaly側の具体的な音源IDと照合したうえで、必要な組だけ提案として取り込めます。
