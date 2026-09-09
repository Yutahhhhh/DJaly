# DDJ-1000 疎通確認（2026-09-09）

## 実機で確認した結果

- IOUSBHostDevice に DDJ-1000 / AlphaTheta Corporation が active として列挙された。
- CoreAudio と DJaly の audio.devices.list の両方で入力12ch・出力6ch、44,100Hzとして列挙された。
- CoreMIDI の送受信エンドポイントが DDJ-1000 として列挙された。クライアント生成・入力ポート生成・ソース接続の OSStatus はすべて0。
- 独立した受信プローブで45秒間にMIDIパケット182件を受信。例: B3 13 0B B3 33 07、B6 1F 7F B6 3F 5F。個々の操作との対応は未同定。
- 実行中アプリと同じ stage/DJalyMixxxHost.app のバイナリを別プロセスで起動し、DJALY_MIXXX_OUTPUT_DEVICE=DDJ-1000 を指定。
- audio.config.get: applied=true、deviceId=DDJ-1000、44,100Hz、256frames、masterChannels=[0,1]、reason空。
- 8秒の無音WAVをロード・再生し、約3秒後にpositionMs=3001.18、positionFrames=132352、status=playing、lastError=nullを確認。プローブは終了済み。

## 現状の制限

- この確認は独立プローブ。起動中のDJalyの出力設定を切り替えたわけではない。
- 実際のスピーカー／ヘッドホンからの発音は未確認。pflApplied=false、pflChannels=null。
- native/mixxx-engine-host/scripts/build-macos.sh と build-upstream/CMakeCache.txt は PORTMIDI=OFF。
- src-tauri/src、src/services/dj-engine、native/mixxx-engine-host/src の調査では、実機MIDI受信・コントローラーマッピング処理は見つからなかった。
- 本体からMacへのMIDI入力は成功しているが、ボタン／ジョグによるDJaly操作とソフトから本体へのLED・表示フィードバックは未対応・未検証。

次の開発対象はMIDI接続とDDJ-1000操作マッピング。今回の結果だけでコントローラー連動完了とは判断しない。
