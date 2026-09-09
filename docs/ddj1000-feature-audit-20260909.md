# DDJ-1000 機能取りこぼし監査 — 2026-09-09

> **この監査は実装前の記録**。以後の実装・修正・検証は [実装と検証 — 2026-09-09](ddj1000-implementation-20260909.md) にある。本書の「現状」欄はその時点のもので、更新していない。

疎通成功はユーザー確認済み。これは**機能網羅性の監査**であり、ハードウェアへの追加送信、アプリ再起動、実装変更は行っていない。Claude Codeとの並行作業に備え、調査時点の対象ファイルのSHA-256を別添に保存。

- 正本: [公式MIDI表453行](ddj1000-midi-map.json)、[説明・原典不整合](ddj1000-midi-map.md)
- 全行結果: [453行のCSV](ddj1000-feature-audit-20260909.csv)。`official_json_row_1based` はJSON配列の1始まり位置。
- 調査対象の版: [SHA-256](ddj1000-feature-audit-20260909.sha256)。後続変更があれば該当項目を再確認する。

公式表は通信アドレス・値域の資料であり、rekordboxの全操作仕様までは規定しない。「通信未処理」「ソフト機能なし」「代替動作」「本体処理のため要実測」を区別した。CSVの「動作経路あり」は完全実装や実機動作確認済みを意味しない。

## 全行の入力プローブ

実際の `Ddj1000Decoder.feed()` に、JSONの入力アドレスを投入した。可変チャンネルは `channel` 欄を展開し、14bit CCはMSB→LSB、OFF専用行は事前にONを入れてからOFFを検査。実機には送信していない。DECK SELECTの固定statusは印字どおりに扱い、原典の矛盾を補正していない。

| 区分 | 原典行数 | 入力あり | アクション生成 | 未デコード |
|---|---:|---:|---:|---:|
| BROWSER | 17 | 17 | 12 | 5 |
| DECK | 47 | 47 | 39 | 8 |
| MIXER | 40 | 40 | 15 | 25 |
| EFFECT | 40 | 40 | 31 | 9 |
| PAD（パッド256＋モード/PAGE40） | 296 | 296 | 266 | 30 |
| 表示専用 | 13 | 0 | — | — |
| 合計 | 453 | 440 | 363 | 77 |

同じ操作のSHIFT・PAGE・OFFや左右重複も別行なので、これは機能数・達成率ではない。256パッド行は全てアクション化されるが、その後の実処理に多くの欠落がある。

## 優先度1: 音声機能・操作の欠落

| 項目 | 現状と根拠 | 実装・確認すべき範囲 |
|---|---|---|
| **SAMPLER全体** | [runtime](../src/services/midi/ddj1000-runtime.ts) の `sampler` はエラーで終了。[PlayWorkspace](../src/components/play/PlayWorkspace.tsx) はパネルstub。ネイティブに `num_samplers` のControlObjectはあるが、サンプラー音声チャンネルの生成・ロード/再生コマンドがない | パッド両PAGE/SHIFT、音源ロード・再生/停止・状態保存、SAMPLER VOL `B6 03/23`、CUE `96 69/6E`、FX割当 `94 16`、状態/LEDまで一式 |
| **キー操作** | `KEYBOARD` / `KEY SHIFT` はエラーのみ。KEY SYNC `9n 65/1C`、KEY RESET `9n 64/1F` は未デコード。MASTER TEMPOのkeylockは別機能として実装済み | キー変更/同期/リセットのエンジンAPI、パッドモード、現在キーと変化量の表示 |
| **SLIP・SLIP REVERSE・REVERSE** | `9n 40/15/38` は受信後エラー。音声への対応コマンド経路なし | 通常の再生位置とSLIP中の位置、押下/解放、逆再生、曲変更時の解除 |
| **MEMORY CUE** | MEMORY `9n 3D/3E` 未デコード。SEARCH+SHIFT `51/53` は保存MEMORYではなく `hotCues` をソートして移動 | MEMORY専用データ・登録/削除・呼出・保存。HOT CUEと混同しない |
| **BEAT FX** | 14種類中 ECHO/REVERB/FLANGER/PHASER の4種類のみ。残る10種は受信するがエラー。BEAT左右 `94 4A/4B/66/6B` とSHIFT+ON/OFF `94 43` は未デコード | 拍数/時間の操作、残りのFX、SHIFT操作。原典のスペル誤記も名称照合時に考慮 |
| **FXの経路・同時使用** | MASTER指定は各ロード済みデッキへ個別にFXを掛ける代替。MIC/SAMPLERは未対応。PAD FXとBEAT FXが同じデッキの1スロットを共有し、後の指定が上書き | 合算後のMASTER bus処理、MIC/SAMPLER入力、PAD FXとBEAT FXの共存設計 |
| **SOUND COLOR FX** | FILTERのみ。D-ECHO/PITCH/NOISEはエラー。SHIFT `96 08–0B` は未デコード | 残る3種類とSHIFT別入力。デコーダーにある `96 10–13=colorState` は公式表にないため、原典由来の状態通知とは扱わない |

## 優先度2: パッドと既存操作の部分実装

| 項目 | 現状と根拠 |
|---|---|
| **HOT CUE PAGE 2** | デコーダーはslot 8–15を保持するが、runtimeで未対応通知。ネイティブ `deck.load` もhotCuesを厳密に8個に制限している。UIだけの追加では不足 |
| **PAD FX 1/2とPAGE** | デコーダーでmode 1と5を両方 `padFx` に変換し、モード差が消える。runtimeの `slot % 8` でPAGE 2もPAGE 1と同じ8FX。SHIFT別処理・別バンク設定もない |
| **BEAT JUMP / BEAT LOOP PAGE 2** | 同じく `%8` でPAGE 1と同じ割当。SHIFTは情報を保持するが実処理で参照しない |
| **PAGEボタン** | 32入力のうち通常BEAT JUMP左右 `9n 26/2E` のみ範囲変更に使用。残る30入力は未デコード。パッド自身のnoteはPAGE情報を含むため、「PAGEボタン未処理＝全パッド受信不能」ではない |
| **LOOP IN/OUT ADJUST** | INで位置を記憶、OUTで区間作成はある。ループ中の境界調整モードとジョグ連携はない。SHIFT+IN `9n 4C` も未デコード |
| **SHIFT+QUANTIZE** | `9n 39` 未デコード。通常QUANTIZEはあり |
| **FADER START** | SHIFT操作 `9n 66/52` とも未デコード。フェーダーによる再生開始/戻り処理なし |
| **SEARCHの意味** | 通常 `9n 5E/5F` はライブラリの選択行移動へ転用。LONG `70/71` は押下時に5秒seekし、保持中の反復タイマーはない。資料のSEARCH操作との同等性は別途操作仕様で確定する |
| **BROWSER** | SHIFT+LOAD `96 5D/5E/6D/6F`、VIEW LONG `96 67` 未デコード。通常LOAD/BROWSEはあり。SHIFT回転は波形ズームに接続済みで、未実装には数えない |
| **SYNC MASTER** | runtimeは他のsync有効deckにleaderを指定し、自deckはsync無効にする。独立したmaster選択状態はなく、他deckがsyncしていない場面も含め動作確認が必要 |
| **DECK SELECT** | `72` はアクション化されるが、押下deckのactivate以外の専用処理なし。原典status矛盾により、1↔3/2↔4の切替先を確定できていない。生バイト取得前に修正しない |
| **SHIFT+CH CUE** | `9n 68` 未デコード。通常 `54` のPFLは実装あり |

根拠: [デコーダー・フィードバック](../src/services/midi/ddj1000.ts)、[runtime](../src/services/midi/ddj1000-runtime.ts)、[SoftwareDeck](../src/components/play/SoftwareDeck.tsx)、[PlayLibrary](../src/components/play/PlayLibrary.tsx)、[ネイティブhost](../native/mixxx-engine-host/src/host.cpp)。

## 優先度2: 本体表示・LEDの欠落

疎通できることと、全表示項目が同期することは別。HID中はMIDI画面指示を抑制しており、MIDI出力コードだけあっても現在の本体表示には反映されない。

| 項目 | 現状 |
|---|---|
| キー値 / キー変化 | 公式 `49/4A` のMIDI出力なし。HIDへキーを渡しておらず、変化相当のbyteは `0x0d` 固定 |
| 残り時間 | MIDIはelapsed固定。HIDも経過時間のみで、切替状態を持たない |
| 一時CUEマーカー | MIDI CC `17/37` 未送信。HIDでは最初のhotcueまたはbeatで代用し、runtime/UIの一時 `cuePoints` と連動しない |
| SYNC / MASTER | MIDI `59/5A` の出力はあるがHID中抑制。HIDの `master` フィールドは未使用、`syncEnabled` 自体を渡していない |
| 再生速度 | MIDI数値出力はあるがHID中抑制。HIDのrateは時間補間に使用し、速度数値表示の経路はない |
| BPM値域 | 公式MIDIは999.9、HID実装は255.9で制限。高BPM表示の互換性は未達 |
| LOOP表示 | HIDではループ状態を渡さず、状態レコードの該当箇所は固定。ソフト上のLOOP動作実装とは別の欠落 |
| パッドLED | 現在送るのは通常チャンネルのHOT CUE/PAD FX 1/BEAT JUMP/BEAT LOOP各PAGE 1のみ。PAGE 2、PAD FX 2、SAMPLER、KEYBOARD、KEY SHIFT、SHIFTチャンネルへの対応出力がない。HOT CUEも固定127で、保存色の反映なし |
| モード/PAGE・FX等のLED | `ddj1000Feedback` にパッドモード/PAGE、BEAT FX ON/OFF・BEAT、SLIP/REVERSE、KEY SYNC等の状態出力がない。未実装機能に伴う欠落も含む。公式OUTの可変statusは実機確認を伴って扱う |

根拠: [MIDI出力](../src/services/midi/ddj1000.ts)、[HIDへのフレーム](../src/services/midi/ddj1000-display.ts)、[HIDレコード](../src-tauri/src/dj_engine/jog_display.rs)、[出力抑制](../src/hooks/useDdj1000.ts)。曲名・画像・波形のHID転送は公式453行の範囲外。画像転送が実装されていても上記の表示欠落を補うものではない。

## 本体処理・実測待ちとして分ける項目

MASTER LEVEL、BOOTH LEVEL、HEADPHONES MIXING/LEVEL、MIC EQ、MIC OFF/ON/TALKOVER、LINE/PHONO、INPUT SELECTは未デコード。MASTER CUEは受信するがruntimeの適用処理はない。

ただし既存の[接続設計](ddj1000-controller.md)は、DDJ-1000の本体処理をソフトで二重に掛けない方針。実際に音量等が効かないと断定しない。必要なのは本体処理の実測、ソフトの状態表示との同期、入力切替時の扱いの確認。ネイティブのマイク入力/ducking機能自体は既にあるため、「マイク機能全体が未実装」とは扱わない。

- **レベルメーター**: 公式表に定義なし。既存のデッキCC `02` 出力は保持中。未定義と誤り確定を混同せず、実機反応を見て判断する。
- **DECK SELECT**: 原典内のstatus矛盾が残る。疎通成功だけでは切替先の確定にならない。

## 検証と引継ぎ

既存テストはデコーダーの一部、ジョグ、各パッドの番号計算等を検証するが、453行すべての最終機能の完成を保証しない。特に `sampler` アクションが生成されるテストに合格しても、音が鳴る実装は存在しない。

最初の実装単位はSAMPLERのロード→パッド再生/停止→音量→CUE→FX割当→状態/LEDまでを縦に通すこと。その後、キー・SLIP/REVERSE・MEMORY・FX操作、パッドのモード/PAGE分離、HID表示を順に埋める。各項目はエンジン、コマンド、runtime、UI、入力、出力を揃えて完了と判定する。

この監査ではアプリの実装ファイルを編集していない。生成したのは本メモ、453行CSV、調査対象のハッシュ一覧のみ。

監査時の再検証: 既存Node MIDI/表示テスト24件成功。CSVは453行が欠番なく並び、全行に分類・所見があることを確認。監査終了時点でSHA-256対象ファイルに調査中の変更はなかった。今回、実機への送信を伴うテストは実行していない。
