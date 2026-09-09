# DDJ-1000 コントローラー連携

## 利用方法

デスクトップ版のPLAY画面を開くとDDJ-1000のMIDIポートに自動接続する。上部は「MIDI入力待ち」「MIDI受信あり」を区別する。本体の認識・LED表示まで保証する表示ではない。接続の有効／無効、今回の接続での受信／送信件数、接続エラー、ジョグ感度を確認できる。MIDIだけを無効にしても音声エンジンは停止しない。

「本体のCUEランプを4秒間点滅」で出力を目視確認できる。音声や再生状態は変えず、終了後は通常のLED表示へ戻す。「MIDIを再接続」でポートを開き直して初期化を再送する。

他社ソフト用の設定は取扱説明書26ページを参照。USBを抜いて電源OFF、左のSHIFT＋PLAY/PAUSEを押しながら電源ON、左のSLIP REVERSEを点灯させ、電源OFFで保存する。rekordboxへ戻す場合は同手順で消灯する。rekordboxが動作していなければ通常は自動的に汎用MIDIになるため、設定だけを原因と断定しない。

音をDDJ-1000から出す場合は「オーディオ」でDDJ-1000を選択・適用する。MASTERはUSB 1/2、ヘッドホンCUEはUSB 3/4。本体の入力切替を接続中のUSB A/Bへ合わせる。マスター・ブース・ヘッドホン音量／ミックス、マイクの本体処理をソフトで重ね掛けしない。

既存の音声出力をMIDI検出だけで切り替えることはない。再生中のデッキには本体のLOADから曲を上書きしない。接続後、必要なEQ・フェーダーを動かしてソフトへ位置を反映する。

## 対応する操作

| 本体 | DJaly |
| --- | --- |
| DECK 1–4 | A–D。3/4操作時は4デッキ表示へ切替 |
| BROWSE／押し込み | 曲一覧の選択／該当デッキへのロード |
| BACK／VIEW／RELATED | Collectionへ戻る／右パネル表示／関連曲表示 |
| SHIFT＋BROWSE | 詳細波形のズーム |
| PLAY | 再生／一時停止 |
| CUE | 再生中は停止してキューへ戻る。停止中に別位置ならキュー設定。キュー位置で保持すると試聴、離すと戻る。保持中のPLAYで再生を継続 |
| SHIFT＋CUE | 曲頭へ移動 |
| ジョグ上面・タッチ | VINYL時のスクラッチ。離すと解除 |
| ジョグ側面 | 再生中は一時的なテンポ補正。停止中は位置調整 |
| SHIFTジョグ | 高速位置調整 |
| TEMPO／MASTER TEMPO | 14bitテンポ／キーロック |
| SHIFT＋MASTER TEMPO | ±6/10/16/WIDE（DJalyの±75）切替。画面と同期 |
| SYNC／SHIFT＋SYNC | 同期／同期基準の変更 |
| QUANTIZE | 量子化 |
| EQ／TRIM／CH FADER／CROSSFADER | 14bit入力。EQは中央1倍、左右端0–4倍。TRIM 0–2倍 |
| クロスフェーダー割り当て | LEFT／THRU／RIGHTをMixxxへ適用 |
| チャンネルCUE | 独立したヘッドホンCUEバス |
| FILTER／COLORノブ | 各チャンネルのフィルター |
| LOOP IN／OUT／HALF／DOUBLE／4 BEAT／EXIT | マニュアル・ビートループ操作 |
| HOT CUEパッド1–8／SHIFT | 登録・呼び出し／削除。既存のメタデータ保存処理を利用 |
| BEAT JUMP／SHIFTモード | 拍移動／BEAT LOOP |
| PAD FX | 画面と同じ8種類の押している間のエフェクト |
| BEAT FX | ECHO／REVERB／FLANGER／PHASER、デッキ／MASTER割り当て、ON/OFF、DEPTH |

LEDはソフトの確認済み状態から更新する。PLAY・CUE・SYNC・キーロック・QUANTIZE・ループ・PFL・ホットキュー・パッドFX・レベルメーターを反映する。ジョグ画面には経過時間、BPM、速度、回転位置を送る。曲名・アートワーク・波形画像のLCD転送は含まない。

## 音声エンジン側の対応範囲

サンプラー、KEYBOARD／KEY SHIFT、SLIP／REVERSE、HOT CUE 9–16、FILTER以外のSOUND COLOR FX、上記以外のBEAT FXとMIC／SAMPLER割り当ては未対応。操作した場合は未対応の理由を画面へ出す。PAD FXとBEAT FXは同じ各デッキのエフェクトスロットを使うため、後から指定したものに切り替わる。MASTERへのBEAT FXはロード済み4デッキへの同時適用。

これはDDJ-1000専用。名前が似たDDJ-1000SRTを自動的に開かない。

## 実装と接続の寿命

- Rustのmidir/CoreMIDIワーカーが入力と出力を保持。CoreMIDIコールバックでは上限付きキューへ送るだけで、エンジン／UI処理をしない。
- MIDIワーカーからAppHandle.emitを呼ばない。最大32バッチの受信箱からUIが16ms間隔・最大16バッチずつIPCで取得する。取得は同時に1回だけ。満杯時は不完全な操作列を破棄し、エラーと切断を経由して押下中の操作を解除する。
- 入力リスナーと接続世代を確定してからPC APP CONNECT（9F 09 7F）を送る。通常の表示差分送信に加え、2秒ごとに表示を再送して、本体の起動遅延時にも回復する。
- 抜き差しを1秒ごとに検出。再接続ごとの世代番号で古い入力／出力を排除する。
- macOSではMIDIワーカーのCFRunLoopを処理して機器変更通知を受け取る。ポート名だけでなくエンドポイント同一性を比較し、同名での再接続でも開き直す。未検出時は入力／出力の検出数を表示する。
- UIからの500ms更新が3秒以上途絶えるとポートとLEDを解除。無効化、PLAY画面終了、アプリ終了時も解除する。
- フロントエンドのデコーダーはノートON/OFF、running status、14bit CC、リアルタイムバイト、SysExを区別する。
- ジョグにはbegin/move/endと200ms heartbeatを使用。高頻度移動は既存のscratchキューで集約する。テンポ／フェーダー／EQも連続入力を集約する。
- セッションとデッキのロード世代を確認して、同じ曲の再ロードを含めて古い操作を捨てる。CUE試聴・押しているPAD FXは切断時に解除する。
- BROWSEは読み込み済み一覧を移動し、末尾に近づくと次ページを要求する。選択行へスクロールする。

## 検証（2026-09-09）

- TypeScript／Viteの本番ビルド。
- MIDIデコーダー・実行処理の16テスト。4デッキ、14bit、符号、分割メッセージ、CUE、連打、切断、同じ曲の再ロード、テンポレンジ、FX入力集約を検証。
- 既存のプロトコル／連続制御／スクラッチキューの回帰テスト。
- Rustユニットテスト。別途、接続済みDDJ-1000で入力／出力ポート、実受信、送信成功、更新停止後の自動解除を検証。
- 配布用stageバイナリ＋接続済みDDJ-1000で、MIDIデコード→実エンジンへの再生／停止、EQ、フェーダー、クロスフェーダー割り当て、ホットキュー登録／削除、ループ、スクラッチ解除、ヘッドホンCUEの統合テスト。
- 音声検証は無音WAV。実際のスピーカー／ヘッドホンの聴感、本体LCD／全LEDの目視、実際のジョグ感度は別途実機操作で確認する。

再実行:

```sh
node --experimental-strip-types --test native/dj-engine-host/tests-node/ddj1000.test.ts
cargo test --manifest-path src-tauri/Cargo.toml --lib
# 接続済みDDJ-1000へのLED送信を含む
cargo test --manifest-path src-tauri/Cargo.toml real_ddj1000_transport -- --ignored --nocapture
# 実機を操作せず、別プロセスの仮想MIDIポートで接続→切断→再接続を検証
cargo test --manifest-path src-tauri/Cargo.toml coremidi_hotplug_reconnect -- --ignored --nocapture
DJALY_MIXXX_OUTPUT_DEVICE=DDJ-1000 node --experimental-strip-types --test native/mixxx-engine-host/tests/ddj1000.test.mjs
```

## 参照

- [DDJ-1000実機マッピング作者によるPC APP CONNECTの記録](https://github.com/mixxxdj/mixxx/wiki/Ddj-1000)
- [Pioneer DJ取扱説明書26ページ（転載）](https://www.manualslib.com/manual/1436395/Pioneer-Dj-Ddj-1000.html?page=26)

- メーカー同梱の `/Applications/rekordbox 7/rekordbox.app/Contents/Resources/MidiMappings/DDJ-1000.midi.csv` を読み取り、操作番号を照合（再配布しない）。
- [Pioneer DJ MIDIメッセージ一覧](https://www.pioneerdj.com/-/media/pioneerdj/software-info/controller/ddj-1000/ddj-1000_midi_message_list_j1.pdf)
- [VirtualDJ公式 DDJ-1000音声設定](https://virtualdj.com/manuals/hardware/pioneer/ddj1000/installation.html)
- [VirtualDJ公式 本体ミキサー操作](https://virtualdj.com/manuals/hardware/pioneer/ddj1000/layout/mixer.html)

## 接続表示の追加検証（同日）

PC APP CONNECT をCoreMIDIから実機へ送信したところOS戻り値は0（成功）だが、前後1秒／2秒の受信は0件。メーカー同梱VersionViewerを起動後の再試行も同じ結果だった。これは本体側の認識成功を証明しない。USB入力切替、本体モード、ドライバー状態と、CUEランプテストの目視確認が残る。アプリ内からの全操作・全表示の実機動作完了とは扱わない。

その後の「再接続後に待機中」の報告では、USBとCoreMIDIの両方が実機を認識し、新規プロセスの実機ポート開放テストも成功した。既存ワーカーで未処理だった機器変更通知への対応とエンドポイント比較を追加。独立したSwiftプロセスで仮想ポートを作成・削除・再作成するテストにより、検出、切断、新しい接続世代での復帰を確認した。実機のボタン入力とLEDの目視確認は継続して必要。

## MIDI受信後のフリーズ修正

実際に停止したPID 48304の3秒間のsampleで、UIスレッドが`WebviewManager::webviews_lock`待ち、MIDIワーカーが`AppHandle.emit → Webview::eval`からUI待ちになっていた。採取結果は `/tmp/djaly-freeze-sample.txt`。受信を契機とするロックの循環待ちを確認したため、MIDIイベントの直接emitを廃止し、`dj_midi_read`による上限付き取得に変更した。音声エンジンの通知経路には変更を加えていない。

受信箱の順序保持・1回の取得上限・UI停止時の非ブロッキング・あふれた操作列の無効化を追加テストで確認。通常ビルドとRustテスト20件が成功。実機の操作中にも画面が応答するかは利用者の確認待ち。
