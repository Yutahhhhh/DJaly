# DDJ-1000 ジョグ画面の公開実装調査

2026-09-09。ユーザーからのMixxx拡張の情報を受けて調査。

## 見つかった実装

- https://github.com/ntamas94/pioneered-by-ntamas/tree/main/ddj1000-jog-display
- https://github.com/ntamas94/pioneered-by-ntamas/blob/main/ddj1000-jog-display/djbox-ddj-bridge.py
- https://github.com/ntamas94/pioneered-by-ntamas/blob/main/ddj1000-jog-display/djbox-ddj-jogdisplay.py
- https://github.com/randombyte-developer/ddj-1000

前者はLinux/Raspberry Pi上のMixxxからジャケット・波形・再生状態をジョグ画面へ送る開発中の実装。通常のMIDIマッピングに加え、SysEx接続応答とheartbeat、HID画面描画を別プロセスが担当する。後者は別のTypeScript製MIDIマッピング。Mixxx本体mainのファイル一覧にはDDJ-1000用マッピングは見つからなかった。

## DJalyとの差分

調査開始時のDJalyはMIDI入力とLED・数値表示用のMIDI出力のみだった。9F 09 7Fだけでは上記の接続処理を代替しない。下記の追加実装でSysEx応答とHID経路を接続した。

公開コードでは、HID usage page 0xFFA0、64バイトreportを使い、0x21の状態レコードを継続送信する。画像は0x2B、波形は0x2Cの分割転送。MIDI表示メッセージとHID表示を混在させると画面が切り替わるとコメントされている。HID方式へ切り替える場合は既存の周期的なMIDI画面再送を整理する必要がある。

Linuxのraw MIDI、hidraw、ALSA、USBリセット処理はmacOSへそのまま持ち込めない。特にUSB転送の一括性、ドライバーとの共存、再接続とheartbeatの寿命をCoreMIDI／IOHIDで別途確認する。公開コードに含まれる収録済み通信の一括再生やドライバー操作は実施していない。

## このMacで確認できたこと

IOHIDManagerで接続中DDJ-1000（VID 0x2B73、PID 0x0020）を読み取り確認。manager openは0、対象1件、usage page 65440（0xFFA0）、usage 1、入力／出力reportは64バイト。公開実装と同じHIDインターフェースが存在する。

メーカーMIDI一覧も新しい配布URLから取得して照合した。
https://downloads.support.alphatheta.com/software_info/dj-controllers/DDJ-1000/DDJ-1000_MIDI_Message_List_E1.pdf

現在使っているBPM、時間、回転位置、画面表示／非表示のアドレスは一覧と一致する。ただし正しいアドレスの送信だけでは本体の画面が利用可能になった証明にはならない。

## macOS向け追加実装

参照した公開版のコミットは `cb93cd6a1dfd917bd660f9d234b4474d89477d42`。公開された通信仕様を基に、Linuxスクリプトの実行・録画済み通信ファイルの一括再生・USBリセット・ドライバー変更は行わず、Rust/CoreMIDI/hidapiで独立した画面ワーカーを実装。

- `src-tauri/src/dj_engine/jog_display.rs`: 接続時のSysEx identity/challenge/ACK、200msのheartbeat、macOS共有HIDアクセス、64バイトreport。互換性のためプロトコル上のidentityは公開実装のrekordbox方式を使うが、アプリの表示名はDJalyのまま。
- `src/services/midi/ddj1000-display.ts`: 600列の波形、BPM・位置・ホットキュー・グリッド、HID中のMIDI画面表示抑制。
- `src/services/midi/ddj1000-display-assets.ts`: 既存メタデータAPIから実際の波形とジャケットを取得。ジャケットは80×80 JPEG。元データに波形がない場合は架空の波形を作らない。
- 入出力はUIスレッドでは実行しない。UIの50ms更新を最新1組のスナップショットとして保持し、曲と画像版数が変わると旧転送を破棄。4デッキの状態を8msの絶対期限で送り、その間に画像転送を進める。USB書き込み時間を周期へ累積させない。
- 旧曲の消去、短い空デッキ表示、曲の通知、グリッド・画像・波形・曲IDの転送。通常再生中の位置をネイティブ側で補間し、スクラッチ中は補間しない。
- 3秒のlease失効で画面を消去してポートを解放。HID/MIDI送信エラー時はポートを開き直し、ACKから再実行。UIへは状態を取得で返し、背景スレッドから直接emitしない。

### 確認結果と限界

接続済み実機からACKを受信し、`authenticated: true` を確認。追加の実機テストでは空デッキのHID report 40件がエラーなしで送信された。これは画面の全内容の目視検証を代替しない。

Rustテスト25件、NodeのMIDI／表示テスト24件、既存の実ネイティブ音声ホスト統合テスト1件が成功。通常ビルド成功。波形・ジャケット・BPM・時間の実画面表示はユーザーの確認待ち。曲名文字列、全てのrekordbox画面モード、実機ループ／キー表示の完全再現を確認済みとはしない。

再実行:

```sh
cargo test --manifest-path src-tauri/Cargo.toml --lib
node --experimental-strip-types --test native/dj-engine-host/tests-node/ddj1000-display.test.ts native/dj-engine-host/tests-node/ddj1000.test.ts
# 実機テスト: 通常のPLAY画面との同時接続を避ける。空デッキを本体へ送る。
cargo test --manifest-path src-tauri/Cargo.toml hardware_handshake --lib -- --ignored --nocapture
```

### 瞬断の追加調査（2026-09-09）

- 実行中アプリを計測すると、ACK受信済み・HID書き込み成功でも、旧スケジューラーでは状態送信が合計314回/秒（約78回/秒/デッキ）だった。公開実装は125回/秒/デッキを要求するため、4デッキを8msの絶対期限で送る方式に変更。
- 公開実装の状態レコードに合わせ、byte 5を常時 `0x81` に修正。これをMASTERフラグとして切り替える根拠はない。
- HIDポートが開いている間は認証待ちも含めてフロントエンドのMIDI画面表示を抑制し、二方式の表示指示の競合を減らす。認証を再要求された場合は10秒の応答待ち時間を開始し直す。
- 一時ディレクトリの `djaly-ddj-display-status.json` に状態送信数/秒、heartbeatの最大送信間隔、最新フレームの経過時間を毎秒上書きする。ファイル書き込み中はUIと共有するロックを保持しない。
- 周期修正後の実行中アプリで合計500回/秒、heartbeat最大207ms、フレーム経過41msを観測。これは送信側の計測であり、本体表示の継続を保証するものではない。最終修正に伴うアプリ再起動後の、曲をロードした状態での目視確認は未完了。
