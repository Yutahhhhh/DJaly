# 選択解析と大量ライブラリの更新

v0.4.1では、MCPから音響解析の項目を選択し、アプリ内の永続ジョブとして実行できる。
既定は`embedding`のみ、解析方式が古い／未解析の曲のみ。同じ曲のBPM・キー・波形・ジャンル・歌詞・音源タグは変更しない。

| features | 更新するデータ |
| --- | --- |
| `embedding` | MusiCNNの音響類似度用ベクトル |
| `rhythm` | BPM、ビート位置、BPM信頼度 |
| `key` | キー、スケール、キー検出の強さ |
| `timbre` | Energy、Danceability、Brightness、Noisiness、Contrast、Loudness等 |
| `waveform` | 表示用波形 |

## MCPでの操作

1. `plan_track_analysis`で対象件数を確認する。`track_ids`・`genres`で絞り込み、`limit`で試行件数を制限できる。省略すると全ライブラリから対象を選ぶ。
2. `start_track_analysis`で開始する。`features`省略時は`["embedding"]`、`only_outdated`は既定でtrue、`workers`は既定2（指定可能範囲1〜4）。結果の`id`がジョブID。
3. `get_track_analysis_status`で完了数、残り件数、残り時間の目安、失敗理由を確認する。ID省略時は最新ジョブ。
4. `pause_track_analysis`で処理中の曲を保存後に一時停止する。
5. `resume_track_analysis`で続きを処理する。`workers`変更、`retry_failed=true`による失敗曲の再試行も可能。

開始例：

```json
{"features":["embedding"],"only_outdated":true,"limit":30,"workers":2}
```

ジョブはMCP接続が切れても継続する。サーバーが停止した場合も完了分は残り、次回起動後に明示的に再開できる。通常のインポートと同時には開始しない。
エラー曲を完了扱いにせず、`completed_with_errors`と曲ごとの理由を返す。

## 処理の仕組み

- 音声を一度だけ読み込み、選択した項目だけ計算する。音源の書き換えやメタデータ取得処理は通らない。
- `embedding`は従来と同じ最大60秒の区間を使い、16kHzへ変換して推論する。速度目的で区間を短縮していない。
- CPU処理は少数の別プロセスに分離する。キューへ投入する実行待ちタスク数も同時処理数までに制限する。
- プロセスを256曲ごとに更新して長時間稼働時のメモリ使用を抑える。ネイティブ演算の内部スレッド数を制限し、過剰な並列化を避ける。
- 既存セットリストに使われている曲を優先する。未処理分と結果は`<ライブラリDBパス>.analysis-jobs.sqlite3`へ記録する。
- 楽曲DBへの書き込みは1曲ごとのトランザクション。書き込み後にジョブの完了記録を更新する。間で終了しても、現行モデルの保存済み結果は再開時にスキップできる。
- 新しい埋め込みは`msd-musicnn-1:musicnn-16khz-v1`として識別する。旧方式と新方式のベクトルを直接比較しない。移行途中の異なる方式の曲同士では、セットリストの接続はBPM・キー等で評価する。
- 解析前後に音源のサイズ・更新時刻を確認し、処理中に変更されたファイルは失敗として再試行対象にする。

## CLIから同じMCPを利用する

```sh
backend/.venv/bin/python scripts/track_analysis_job.py plan --features embedding
backend/.venv/bin/python scripts/track_analysis_job.py start --features embedding --limit 30 --workers 2
backend/.venv/bin/python scripts/track_analysis_job.py status
backend/.venv/bin/python scripts/track_analysis_job.py pause --job-id JOB_ID
backend/.venv/bin/python scripts/track_analysis_job.py resume --job-id JOB_ID --workers 4
backend/.venv/bin/python scripts/track_analysis_job.py watch --job-id JOB_ID --interval 60
```

既定接続先は`http://127.0.0.1:48123/mcp`。`--url`で変更可能。
全件対象にするときは`--limit`を外す。過去に成功した現行解析の曲は、別ジョブであっても既定でスキップする。
`watch`は進捗をJSON行形式で出力し、完了・一時停止・失敗時に終了する。接続失敗で勝手に再開はしない。Macでは`caffeinate -i`の後にこの監視コマンドを指定すると、監視中のアイドルスリープを防止できる（蓋を閉じた際のスリープは防止しない）。

## 検証

バックエンド全体187テストが通過。タグ・歌詞・BPM・波形保持、中断再開、異常結果を保存しないこと、失敗曲の再試行、新旧モデルの比較分離、実MCPクライアントからのジョブ操作を含む。
配布用バイナリを検証用DBで起動し、実音源3曲のembeddingのみを2プロセスで更新して成功した。

`scripts/audit_analysis_library.py`は停止中のDBまたはバックアップを読み取り専用で確認する。`--reference`へ更新前のDBを指定すると、楽曲メタデータ・歌詞・セットリスト・ビート・波形の保持を照合できる。
音響解析以外の手編集が行われれば差分になるため、比較するタイミングを揃える。
