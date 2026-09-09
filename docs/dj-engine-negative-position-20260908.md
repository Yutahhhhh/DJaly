# 曲頭前を同じ音声時計で再生する修正

## 契約

曲頭前は別の PRE モードではない。負の `positionMs` / `positionFrames` を持つ通常のトランスポートである。再生中に引き戻して離せば、負の区間を無音で進み、0 秒を通過するとファイルの音が鳴る。停止・再開・テンポは正の位置と同じ操作。波形は同じエンジン位置を表示する。

## 原因と変更

修正前の CoreAudio / BlackHole 2ch 実測では、ドラッグ保持中の内部位置が **−1501.944 ms** なのに、`state.snapshot` は **0 ms**。Mixxx 内部は負の位置をすでに連続再生していた。

- `Host::sampleDeck()` の 0 秒への丸めを撤去。イベントとスナップショットに負の位置を通す。
- `PlayWorkspace` の PRE 状態、開始待ちタイマー、100 ms 再描画タイマー、見かけの位置上書きを削除。
- `DeckWaveform` の停止中だけ PRE に切り替える分岐を削除。再生中・停止中・曲頭前後ですべて同じ scratch begin/move/end を使う。
- スクロール波形の負の位置制限を撤去。無音区間の背景と通常の負の経過時間を表示する。全体概要波形はファイル範囲を表示する。
- 明示 seek は −60 秒まで許可。これはコマンド入力の範囲制限であり、内部再生位置や繰り返しドラッグの通知を切り詰める制限ではない。

音声コールバックの新規処理・ロック・確保・曲頭でのシークは追加していない。固定 upstream も変更していない。

## 計測

追加した `native/mixxx-engine-host/tests/negative-position.test.mjs` で、437.3 Hz の音源を再生中に 1800 ms 引き戻し、保持・解放・曲頭通過を測定する。

- 修正後は通知位置と内部位置がともに約 −1496 ms で一致。
- 解放後は負の区間から正の区間まで単調・実速度 1.0 ± 0.1。曲頭で追加の play / seek は送らない。
- 録音の曲頭前 460 ms 区間は全サンプルが無音判定内。音声時計から予測した曲頭と録音の発音位置の差は約 5.6 ms（録音開始とのバッファ整列誤差を含む）。
- 負の絶対 seek は −1200 ms に停止し、停止中にさらに引き戻すと −1600 ms。再開すると 1.2 倍速で曲頭を連続通過。
- 通知と内部トレース、録音 WAV はテストの一時ディレクトリに保存。修正前: `djaly-negative-Fl0PCr`、修正後の一式実行: `djaly-negative-FmuXbD`（macOS の一時ディレクトリ配下）。
- 配置済みホストでも 48 kHz 音源で合格。通知 −1496.145201 ms、内部 −1496.145201 ms、録音発音差 5.590 ms。証拠: `djaly-negative-jZvhj9`。

既存の scratch / seek-drag / dj-controls / beatgrid / variable-beatgrid / protocol / first-fx / recording-finalization / timing と今回の追加テストを直列実行し、12 件すべて合格。`native/dj-engine-host/tests-node/*.test.ts` は 73 件すべて合格。upstream / seam ホストのビルド、TypeScript 検査、`git diff --check` を通過。`pnpm dj-engine:stage` による配置と署名も完了。

位置描画ヘルパーの単体テストも、特別なモードなしに負の位置を保持し、テンポに従って 0 を越える契約へ更新した。実アプリ画面と物理出音の同時撮影によるエンドツーエンド遅延測定は行っていない。今回の計測は内部音声時計・プロトコル・録音 PCM と表示ロジックのテストであり、OS 入力・描画・DAC 遅延を含むゼロ遅延を主張するものではない。

```sh
node --test native/mixxx-engine-host/tests/negative-position.test.mjs
DJALY_TIMING_SOURCE_RATE=48000 DJALY_TEST_HOST=native/mixxx-engine-host/stage/DJalyMixxxHost.app/Contents/MacOS/djaly-mixxx-engine-host node --test native/mixxx-engine-host/tests/negative-position.test.mjs
```
