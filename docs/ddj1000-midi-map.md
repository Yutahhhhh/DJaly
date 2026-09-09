# DDJ-1000 MIDI メッセージ一覧

DDJ-1000（rekordbox 版、`DDJ-1000SRT` ではない）が汎用 MIDI モードで送受信するメッセージの全一覧。**453 メッセージ**を Pioneer DJ 公式の "List of MIDI message version 1.00" から機械抽出した。DDJ-1000 を汎用 MIDI で使う手順は取扱説明書26ページ、DJaly 側の対応範囲は `docs/ddj1000-controller.md` を参照。

## 出典

同じ 453 行を機械可読にしたものが `docs/ddj1000-midi-map.json`（1 行 1 メッセージ）。コード生成やテーブル生成にはこちらを使う。


| 資料 | 内容 |
| --- | --- |
| [pestrela/ddj — `1 MIDI codes/DDJ-1000RB - MIDI Messages.pdf`](https://github.com/pestrela/ddj) | Pioneer DJ 公式の MIDI メッセージ表（8ページ）。この一覧の一次ソース |
| [mixxxdj/mixxx wiki — DDJ-1000](https://github.com/mixxxdj/mixxx/wiki/ddj-1000) | 未文書メッセージ（PC APP CONNECT）と本体内部モードの制約 |
| [randombyte-developer/ddj-1000](https://github.com/randombyte-developer/ddj-1000) | Mixxx 向けコミュニティマッピング（TypeScript → `pioneer-ddj1000.midi.xml`）。2デッキ |
| [ntamas94/pioneered-by-ntamas](https://github.com/ntamas94/pioneered-by-ntamas) | 同マッピングに 4デッキ版スクリプトとジョグ画面ブリッジを追加したもの |

Mixxx 本体（2.5.6 時点、`native/mixxx-engine-host/upstream/res/controllers/`）は DDJ-1000 のマッピングを同梱していない。同梱されている Pioneer 機種は DDJ-200 / 400 / FLX4 / SB / SB2 / SB3 / SX のみ。

## MIDI チャンネル割り当て

チャンネル番号は1始まり。括弧内は0始まり（ステータスバイトの下位ニブル）。

| チャンネル | 用途 | Note ステータス | CC ステータス |
| --- | --- | --- | --- |
| 1–4 (0x0–0x3) | DECK 1–4（PERFORMANCE PAD 以外） | `90`–`93` | `B0`–`B3` |
| 5 (0x4) | EFFECT（BEAT FX） | `94` | `B4` |
| 6 (0x5) | 未使用 | — | — |
| 7 (0x6) | BROWSER・ミキサー共通部・COLOR FX | `96` | `B6` |
| 8, 10, 12, 14 (0x7, 0x9, 0xB, 0xD) | DECK 1–4 の PERFORMANCE PAD（SHIFT なし） | `97`, `99`, `9B`, `9D` | — |
| 9, 11, 13, 15 (0x8, 0xA, 0xC, 0xE) | DECK 1–4 の PERFORMANCE PAD（SHIFT あり） | `98`, `9A`, `9C`, `9E` | — |
| 16 (0xF) | 公式表に記載なし。PC APP CONNECT に使用 | `9F` | — |

表中の `9n` / `Bn` は n = デッキ番号−1、`9p` はパッドチャンネル（上表）を指す。

## 読み方

- **ボタン** — 押下で `hh` = `0x7F`、離すと `0x00`。Note Off（`8n`）は使わず Note On の velocity 0 で表現する機種ではなく、`9n` の値 0/127 で送る。
- **SHIFT** — SHIFT 自体が Note（`0x3F`）として送られ、SHIFT 併用時は**別の Note 番号**になる。押下状態を見て分岐するのではなく、番号で分岐できる。
- **14bit CC** — フェーダー・EQ・つまみは MSB と LSB の2本の CC で送る。LSB の CC 番号は MSB + 32。実効分解能 0–16383。
- **ジョグ** — 相対値。時計回りは 65 (`0x41`) から増加、反時計回りは 63 (`0x3F`) から減少。プラッター上面・側面・SEARCH 併用・SHIFT 併用で CC 番号が分かれる。
- **MIDI-OUT** — 「← Same as MIDI-IN」の行は、同じステータス／Data 1 をホストから送り返すと LED が点く。それ以外は入力専用（LED を持たない操作子）。
- **PAD の LED** — Data 2 に 1–127 の色番号を入れると該当色で点灯、`0x00` で減光。

## DECK（ch 1–4）

| Fig | コントロール | 修飾 | 動作 | 条件 | ch | 種別 | Data 1 (dec) | Status | Data 1 (hex) | Data 2 | 備考 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| D1-L D1-R | PLAY/PAUSE | — | press | — | 1/2/3/4 | NOTE | `11` | `9n` | `0B` | `hh` | OFF=0x00 / ON=0x7F |
| D1-L D1-R | PLAY/PAUSE | +SHIFT | press | — | 1/2/3/4 | NOTE | `71` | `9n` | `47` | `hh` | OFF=0x00 / ON=0x7F |
| D2-L D2-R | CUE | — | press | — | 1/2/3/4 | NOTE | `12` | `9n` | `0C` | `hh` | OFF=0x00 / ON=0x7F |
| D2-L D2-R | CUE | +SHIFT | press | — | 1/2/3/4 | NOTE | `72` | `9n` | `48` | `hh` | OFF=0x00 / ON=0x7F |
| D3-L D3-R | JOG (Platter) | — | rotate | Vinyl On | 1/2/3/4 | CC | `34` | `Bn` | `22` | `hh` | 相対値（前回操作からの差分）。CW: 65 (0x41) から増加 / CCW: 63 (0x3F) から減少 |
| D3-L D3-R | JOG (Platter) | — | rotate | Vinyl Off | 1/2/3/4 | CC | `35` | `Bn` | `23` | `hh` | 相対値（前回操作からの差分）。CW: 65 (0x41) から増加 / CCW: 63 (0x3F) から減少 |
| D3-L D3-R | JOG (Platter) | +SEARCH | rotate | — | 1/2/3/4 | CC | `41` | `Bn` | `29` | `hh` | 相対値（前回操作からの差分）。CW: 65 (0x41) から増加 / CCW: 63 (0x3F) から減少 |
| D3-L D3-R | JOG (Platter) | +SHIFT | rotate | — | 1/2/3/4 | CC | `31` | `Bn` | `1F` | `hh` | 相対値（前回操作からの差分）。CW: 65 (0x41) から増加 / CCW: 63 (0x3F) から減少 |
| D3-L D3-R | JOG (Platter) | — | touch | — | 1/2/3/4 | NOTE | `54` | `9n` | `36` | `hh` | OFF=0x00 / ON=0x7F |
| D3-L D3-R | JOG (Platter) | +SHIFT | touch | — | 1/2/3/4 | NOTE | `103` | `9n` | `67` | `hh` | OFF=0x00 / ON=0x7F |
| D3-L D3-R | JOG (Platter) | — | rotate | — | 1/2/3/4 | CC | `33` | `Bn` | `21` | `hh` | 相対値（前回操作からの差分）。CW: 65 (0x41) から増加 / CCW: 63 (0x3F) から減少 |
| D3-L D3-R | JOG (Platter) | +SHIFT | rotate | — | 1/2/3/4 | CC | `38` | `Bn` | `26` | `hh` | 相対値（前回操作からの差分）。CW: 65 (0x41) から増加 / CCW: 63 (0x3F) から減少 |
| D4-L D4-R | Tempo | — | slide | — | 1/2/3/4 | CC | `0 32` | `Bn` | `00 20` | `MSB LSB` | 0–16383。−側=Min / ＋側=Max |
| D4-L D4-R | Tempo | +SHIFT | slide | — | 1/2/3/4 | CC | `5 37` | `Bn` | `05 25` | `MSB LSB` | 0–16383。−側=Min / ＋側=Max |
| D5-L D5-R | MASTER TEMPO | — | press | — | 1/2/3/4 | NOTE | `26` | `9n` | `1A` | `hh` | OFF=0x00 / ON=0x7F |
| D5-L D5-R | MASTER TEMPO | +SHIFT | press | — | 1/2/3/4 | NOTE | `96` | `9n` | `60` | `hh` | OFF=0x00 / ON=0x7F |
| D6-L | DECK SELECT 1/3 | — | press | DECK 3 | 1 | NOTE | `114` | `92` | `72` | `hh` | OFF=0x00 / ON=0x7F |
| D6-L | DECK SELECT 1/3 | — | press | DECK 1 | 3 | NOTE | `114` | `92` | `72` | `hh` | OFF=0x00 / ON=0x7F |
| D6-R | DECK SELECT 2/4 | — | press | DECK 4 | 2 | NOTE | `114` | `93` | `72` | `hh` | OFF=0x00 / ON=0x7F |
| D6-R | DECK SELECT 2/4 | — | press | DECK 2 | 4 | NOTE | `114` | `93` | `72` | `hh` | OFF=0x00 / ON=0x7F |
| D7-L D7-R | BEAT SYNC | — | press | — | 1/2/3/4 | NOTE | `88` | `9n` | `58` | `hh` | OFF=0x00 / ON=0x7F |
| D7-L D7-R | BEAT SYNC | +SHIFT | press | — | 1/2/3/4 | NOTE | `92` | `9n` | `5C` | `hh` | OFF=0x00 / ON=0x7F |
| D8-L D8-R | KEY SYNC | — | press | — | 1/2/3/4 | NOTE | `101` | `9n` | `65` | `hh` | OFF=0x00 / ON=0x7F |
| D8-L D8-R | KEY SYNC | +SHIFT | press | — | 1/2/3/4 | NOTE | `28` | `9n` | `1C` | `hh` | OFF=0x00 / ON=0x7F |
| D9-L D9-R | KEY RESET | — | press | — | 1/2/3/4 | NOTE | `100` | `9n` | `64` | `hh` | OFF=0x00 / ON=0x7F |
| D9-L D9-R | KEY RESET | +SHIFT | press | — | 1/2/3/4 | NOTE | `31` | `9n` | `1F` | `hh` | OFF=0x00 / ON=0x7F |
| D10-L D10-R | LOOP IN | — | press | — | 1/2/3/4 | NOTE | `16` | `9n` | `10` | `hh` | OFF=0x00 / ON=0x7F |
| D10-L D10-R | LOOP IN | +SHIFT | press | — | 1/2/3/4 | NOTE | `76` | `9n` | `4C` | `hh` | OFF=0x00 / ON=0x7F |
| D11-L D11-R | LOOP OUT | — | press | — | 1/2/3/4 | NOTE | `17` | `9n` | `11` | `hh` | OFF=0x00 / ON=0x7F |
| D11-L D11-R | LOOP OUT | +SHIFT | press | — | 1/2/3/4 | NOTE | `77` | `9n` | `4D` | `hh` | OFF=0x00 / ON=0x7F |
| D12-L D12-R | 4 BEAT LOOP/EXIT | — | press | — | 1/2/3/4 | NOTE | `20` | `9n` | `14` | `hh` | OFF=0x00 / ON=0x7F |
| D12-L D12-R | 4 BEAT LOOP/EXIT | +SHIFT | press | — | 1/2/3/4 | NOTE | `80` | `9n` | `50` | `hh` | OFF=0x00 / ON=0x7F |
| D13-L D13-R | QUANTIZE | — | press | — | 1/2/3/4 | NOTE | `53` | `9n` | `35` | `hh` | OFF=0x00 / ON=0x7F |
| D13-L D13-R | QUANTIZE | +SHIFT | press | — | 1/2/3/4 | NOTE | `57` | `9n` | `39` | `hh` | OFF=0x00 / ON=0x7F |
| D14-L D14-R | SLIP | — | press | — | 1/2/3/4 | NOTE | `64` | `9n` | `40` | `hh` | OFF=0x00 / ON=0x7F |
| D14-L D14-R | SLIP | +SHIFT | press | — | 1/2/3/4 | NOTE | `23` | `9n` | `17` | `hh` | OFF=0x00 / ON=0x7F |
| D15-L D15-R | SLIP REVERSE | — | press | — | 1/2/3/4 | NOTE | `21` | `9n` | `15` | `hh` | OFF=0x00 / ON=0x7F |
| D15-L D15-R | SLIP REVERSE | +SHIFT | press | — | 1/2/3/4 | NOTE | `56` | `9n` | `38` | `hh` | OFF=0x00 / ON=0x7F |
| D16-L D16-R | SEARCH ◀◀ | — | press | — | 1/2/3/4 | NOTE | `94` | `9n` | `5E` | `hh` | OFF=0x00 / ON=0x7F |
| D16-L D16-R | SEARCH ◀◀ | LONG | press | — | 1/2/3/4 | NOTE | `112` | `9n` | `70` | `hh` | OFF=0x00 / ON=0x7F |
| D16-L D16-R | SEARCH ◀◀ | +SHIFT | press | — | 1/2/3/4 | NOTE | `81` | `9n` | `51` | `hh` | OFF=0x00 / ON=0x7F |
| D17-L D17-R | SEARCH ▶▶ | — | press | — | 1/2/3/4 | NOTE | `95` | `9n` | `5F` | `hh` | OFF=0x00 / ON=0x7F |
| D17-L D17-R | SEARCH ▶▶ | LONG | press | — | 1/2/3/4 | NOTE | `113` | `9n` | `71` | `hh` | OFF=0x00 / ON=0x7F |
| D17-L D17-R | SEARCH ▶▶ | +SHIFT | press | — | 1/2/3/4 | NOTE | `83` | `9n` | `53` | `hh` | OFF=0x00 / ON=0x7F |
| D18-L D18-R | MEMORY | — | press | — | 1/2/3/4 | NOTE | `61` | `9n` | `3D` | `hh` | OFF=0x00 / ON=0x7F |
| D18-L D18-R | MEMORY | +SHIFT | press | — | 1/2/3/4 | NOTE | `62` | `9n` | `3E` | `hh` | OFF=0x00 / ON=0x7F |
| D19-L D19-R | SHIFT | — | press | — | 1/2/3/4 | NOTE | `63` | `9n` | `3F` | `hh` | OFF=0x00 / ON=0x7F |

## MIXER

クロスフェーダー・マスター・ヘッドホン・マイクは ch 7、チャンネルストリップは ch 1–4。

| Fig | コントロール | 修飾 | 動作 | 条件 | ch | 種別 | Data 1 (dec) | Status | Data 1 (hex) | Data 2 | 備考 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| M1 | CROSSFADER | — | slide | — | 7 | CC | `31 63` | `B6` | `1F 3F` | `MSB LSB` | 0–16383。左端=Min / 右端=Max |
| M2-1 M2-2 M2-3 M2-4 | CH FADER | — | slide | — | 1/2/3/4 | CC | `19 51` | `Bn` | `13 33` | `MSB LSB` | 0–16383。下端=Min / 上端=Max |
| M1 M2-1 M2-2 M2-3 M2-4 | CROSS FADER / CH FADER (Fader Start) | +SHIFT | slide | Zero → not Zero | 1/2/3/4 | NOTE | `102` | `9n` | `66` | `hh` | CH フェーダースタートでは PLAY のみ。OFF=0x00 / ON=0x7F |
| M1 M2-1 M2-2 M2-3 M2-4 | CROSS FADER / CH FADER (Fader Start) | +SHIFT | slide | Not Zero → Zero | 1/2/3/4 | NOTE | `82` | `9n` | `52` | `hh` | CH フェーダースタートでは CUE のみ。OFF=0x00 / ON=0x7F |
| M3-1 M3-2 M3-3 M3-4 | GAIN (TRIM) | — | rotate | — | 1/2/3/4 | CC | `4 36` | `Bn` | `04 24` | `MSB LSB` | 0–16383。反時計回り端=Min / 時計回り端=Max |
| M4-1 M4-2 M4-3 M4-4 | EQ HI | — | rotate | — | 1/2/3/4 | CC | `7 39` | `Bn` | `07 27` | `MSB LSB` | 0–16383。反時計回り端=Min / 時計回り端=Max |
| M5-1 M5-2 M5-3 M5-4 | EQ MID | — | rotate | — | 1/2/3/4 | CC | `11 43` | `Bn` | `0B 2B` | `MSB LSB` | 0–16383。反時計回り端=Min / 時計回り端=Max |
| M6-1 M6-2 M6-3 M6-4 | EQ LOW | — | rotate | — | 1/2/3/4 | CC | `15 47` | `Bn` | `0F 2F` | `MSB LSB` | 0–16383。反時計回り端=Min / 時計回り端=Max |
| M7-1 M7-2 M7-3 M7-4 | CUE (Headphone) | — | press | — | 1/2/3/4 | NOTE | `84` | `9n` | `54` | `hh` | OFF=0x00 / ON=0x7F |
| M7-1 M7-2 M7-3 M7-4 | CUE (Headphone) | +SHIFT | press | — | 1/2/3/4 | NOTE | `104` | `9n` | `68` | `hh` | OFF=0x00 / ON=0x7F |
| M8 | MASTER LEVEL | — | rotate | — | 7 | CC | `8 40` | `B6` | `08 28` | `MSB LSB` | 0–16383 |
| M9 | MASTER CUE | — | press | — | 7 | NOTE | `99` | `96` | `63` | `hh` | LED は本体側でも MIDI-OUT でも点灯する |
| M9 | MASTER CUE | +SHIFT | press | — | 7 | NOTE | `98` | `96` | `62` | `hh` | — |
| M10 | BOOTH LEVEL | — | rotate | — | 7 | CC | `9 41` | `B6` | `09 29` | `MSB LSB` | 0–16383 |
| M11-1 M11-2 M11-3 M11-4 | CRF ASSIGN | — | slide | Switch to A | 1/2/3/4 | NOTE | `22` | `9n` | `16` | `7F` | ON=0x7F |
| M11-1 M11-2 M11-3 M11-4 | CRF ASSIGN | — | slide | Switch to A | 1/2/3/4 | NOTE | `24/29` | `9n` | `18/1D` | `00` | OFF=0x00 |
| M11-1 M11-2 M11-3 M11-4 | CRF ASSIGN | — | slide | Switch to THRU | 1/2/3/4 | NOTE | `29` | `9n` | `1D` | `7F` | ON=0x7F |
| M11-1 M11-2 M11-3 M11-4 | CRF ASSIGN | — | slide | Switch to THRU | 1/2/3/4 | NOTE | `22/24` | `9n` | `16/18` | `00` | OFF=0x00 |
| M11-1 M11-2 M11-3 M11-4 | CRF ASSIGN | — | slide | Switch to B | 1/2/3/4 | NOTE | `24` | `9n` | `18` | `7F` | ON=0x7F |
| M11-1 M11-2 M11-3 M11-4 | CRF ASSIGN | — | slide | Switch to B | 1/2/3/4 | NOTE | `22/29` | `9n` | `16/1D` | `00` | OFF=0x00 |
| M12 | HEADPHONES MIXING | — | rotate | — | 7 | CC | `12 44` | `B6` | `0C 2C` | `MSB LSB` | 0–16383 |
| M13 | HEADPHONES LEVEL | — | rotate | — | 7 | CC | `13 45` | `B6` | `0D 2D` | `MSB LSB` | 0–16383 |
| M14 | MIC EQ HI | — | rotate | — | 7 | CC | `7 39` | `B6` | `07 27` | `MSB LSB` | 0–16383。反時計回り端=Min / 時計回り端=Max |
| M15 | MIC EQ LOW | — | rotate | — | 7 | CC | `15 47` | `B6` | `0F 2F` | `MSB LSB` | 0–16383。反時計回り端=Min / 時計回り端=Max |
| M16-1 M16-2 | LINE/PHONO SW | — | slide | — | 3/4 | NOTE | `70` | `9n` | `46` | `hh` | PHONO=0x00 / LINE=0x7F |
| M17-1 M17-2 M17-3 M17-4 | INPUT SELECT | — | slide | Switch to USB A | 1/2/3/4 | NOTE | `85` | `9n` | `55` | `7F` | OFF=0x00 / ON=0x7F |
| M17-1 M17-2 M17-3 M17-4 | INPUT SELECT | — | slide | Switch to USB A | 1/2/3/4 | NOTE | `86/87` | `9n` | `56/57` | `00` | OFF=0x00 / ON=0x7F |
| M17-1 M17-2 M17-3 M17-4 | INPUT SELECT | — | slide | Switch to LINE or PHONO/LINE | 1/2/3/4 | NOTE | `86` | `9n` | `56` | `7F` | OFF=0x00 / ON=0x7F |
| M17-1 M17-2 M17-3 M17-4 | INPUT SELECT | — | slide | Switch to LINE or PHONO/LINE | 1/2/3/4 | NOTE | `85/87` | `9n` | `55/57` | `00` | OFF=0x00 / ON=0x7F |
| M17-1 M17-2 M17-3 M17-4 | INPUT SELECT | — | slide | Switch to USB B | 1/2/3/4 | NOTE | `87` | `9n` | `57` | `7F` | OFF=0x00 / ON=0x7F |
| M17-1 M17-2 M17-3 M17-4 | INPUT SELECT | — | slide | Switch to USB B | 1/2/3/4 | NOTE | `85/86` | `9n` | `55/56` | `00` | OFF=0x00 / ON=0x7F |
| M18 | MIC OFF/ON /TALKOVER | — | slide | Switch to OFF | 7 | NOTE | `106` | `96` | `6A` | `7F` | OFF=0x00 / ON=0x7F |
| M18 | MIC OFF/ON /TALKOVER | — | slide | Switch to OFF | 7 | NOTE | `107/108` | `96` | `6B/6C` | `00` | OFF=0x00 / ON=0x7F |
| M18 | MIC OFF/ON /TALKOVER | — | slide | Switch to ON | 7 | NOTE | `107` | `96` | `6B` | `7F` | OFF=0x00 / ON=0x7F |
| M18 | MIC OFF/ON /TALKOVER | — | slide | Switch to ON | 7 | NOTE | `106/108` | `96` | `6A/6C` | `00` | OFF=0x00 / ON=0x7F |
| M18 | MIC OFF/ON /TALKOVER | — | slide | Switch to TALK OVER | 7 | NOTE | `108` | `96` | `6C` | `7F` | OFF=0x00 / ON=0x7F |
| M18 | MIC OFF/ON /TALKOVER | — | slide | Switch to TALK OVER | 7 | NOTE | `106/107` | `96` | `6A/6B` | `00` | OFF=0x00 / ON=0x7F |
| M19 | SAMPLER CUE | — | press | — | 7 | NOTE | `105` | `96` | `69` | `hh` | OFF=0x00 / ON=0x7F |
| M19 | SAMPLER CUE | +SHIFT | press | — | 7 | NOTE | `110` | `96` | `6E` | `hh` | OFF=0x00 / ON=0x7F |
| M20 | SAMPLER VOL | — | rotate | — | 7 | CC | `3 35` | `B6` | `03 23` | `MSB LSB` | 0–16383。反時計回り端=Min / 時計回り端=Max |

## EFFECT

BEAT FX（`F6`–`F11`）は ch 5、SOUND COLOR FX（`F1`–`F5`）は ch 7。`F8` FX SELECT と `F9` CH SELECT はロータリースイッチで、選択位置ごとに固有の Note を出す。

| Fig | コントロール | 修飾 | 動作 | 条件 | ch | 種別 | Data 1 (dec) | Status | Data 1 (hex) | Data 2 | 備考 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| F1-1 F1-2 F1-3 F1-4 | COLOR FX Parameter (CH1) | — | rotate | — | 7 | CC | `23 55` | `B6` | `17 37` | `MSB LSB` | 0–16383。反時計回り端=Min / 時計回り端=Max |
| F1-1 F1-2 F1-3 F1-4 | COLOR FX Parameter (CH2) | — | rotate | — | 7 | CC | `24 56` | `B6` | `18 38` | `MSB LSB` | 0–16383。反時計回り端=Min / 時計回り端=Max |
| F1-1 F1-2 F1-3 F1-4 | COLOR FX Parameter (CH3) | — | rotate | — | 7 | CC | `25 57` | `B6` | `19 39` | `MSB LSB` | 0–16383。反時計回り端=Min / 時計回り端=Max |
| F1-1 F1-2 F1-3 F1-4 | COLOR FX Parameter (CH4) | — | rotate | — | 7 | CC | `26 58` | `B6` | `1A 3A` | `MSB LSB` | 0–16383。反時計回り端=Min / 時計回り端=Max |
| F2 | COLOR FX (D-ECHO) | — | rotate | — | 7 | NOTE | `0` | `96` | `00` | `hh` | OFF=0x00 / ON=0x7F |
| F2 | COLOR FX (D-ECHO) | +SHIFT | rotate | — | 7 | NOTE | `8` | `96` | `08` | `hh` | OFF=0x00 / ON=0x7F |
| F3 | COLOR FX (PITCH) | — | rotate | — | 7 | NOTE | `1` | `96` | `01` | `hh` | OFF=0x00 / ON=0x7F |
| F3 | COLOR FX (PITCH) | +SHIFT | rotate | — | 7 | NOTE | `9` | `96` | `09` | `hh` | OFF=0x00 / ON=0x7F |
| F4 | COLOR FX (NOISE) | — | rotate | — | 7 | NOTE | `2` | `96` | `02` | `hh` | OFF=0x00 / ON=0x7F |
| F4 | COLOR FX (NOISE) | +SHIFT | rotate | — | 7 | NOTE | `10` | `96` | `0A` | `hh` | OFF=0x00 / ON=0x7F |
| F5 | COLOR FX (FILTER) | — | rotate | — | 7 | NOTE | `3` | `96` | `03` | `hh` | OFF=0x00 / ON=0x7F |
| F5 | COLOR FX (FILTER) | +SHIFT | rotate | — | 7 | NOTE | `11` | `96` | `0B` | `hh` | OFF=0x00 / ON=0x7F |
| F6 | BEAT ◀ | — | press | — | 5 | NOTE | `74` | `94` | `4A` | `hh` | OFF=0x00 / ON=0x7F |
| F6 | BEAT ◀ | +SHIFT | press | — | 5 | NOTE | `102` | `94` | `66` | `hh` | OFF=0x00 / ON=0x7F |
| F7 | BEAT ▶ | — | press | — | 5 | NOTE | `75` | `94` | `4B` | `hh` | OFF=0x00 / ON=0x7F |
| F7 | BEAT ▶ | +SHIFT | press | — | 5 | NOTE | `107` | `94` | `6B` | `hh` | OFF=0x00 / ON=0x7F |
| F8 | FX SELECT (LOW CUT ECHO) | — | rotate | — | 5 | NOTE | `32` | `94` | `20` | `hh` | OFF=0x00 / ON=0x7F |
| F8 | FX SELECT (ECHO) | — | rotate | — | 5 | NOTE | `33` | `94` | `21` | `hh` | OFF=0x00 / ON=0x7F |
| F8 | FX SELECT (MT DELAY) | — | rotate | — | 5 | NOTE | `34` | `94` | `22` | `hh` | OFF=0x00 / ON=0x7F |
| F8 | FX SELECT (SPIRAL) | — | rotate | — | 5 | NOTE | `35` | `94` | `23` | `hh` | OFF=0x00 / ON=0x7F |
| F8 | FX SELECT (REVERB) | — | rotate | — | 5 | NOTE | `36` | `94` | `24` | `hh` | OFF=0x00 / ON=0x7F |
| F8 | FX SELECT (TRANS) | — | rotate | — | 5 | NOTE | `37` | `94` | `25` | `hh` | OFF=0x00 / ON=0x7F |
| F8 | FX SELECT (ENIGMA JET) | — | rotate | — | 5 | NOTE | `38` | `94` | `26` | `hh` | OFF=0x00 / ON=0x7F |
| F8 | FX SELECT (FLANGER) | — | rotate | — | 5 | NOTE | `39` | `94` | `27` | `hh` | OFF=0x00 / ON=0x7F |
| F8 | FX SELECT (PHASER) | — | rotate | — | 5 | NOTE | `40` | `94` | `28` | `hh` | OFF=0x00 / ON=0x7F |
| F8 | FX SELECT (PITCH) | — | rotate | — | 5 | NOTE | `41` | `94` | `29` | `hh` | OFF=0x00 / ON=0x7F |
| F8 | FX SELECT (SLPI ROLL) | — | rotate | — | 5 | NOTE | `42` | `94` | `2A` | `hh` | OFF=0x00 / ON=0x7F |
| F8 | FX SELECT (ROLL) | — | rotate | — | 5 | NOTE | `43` | `94` | `2B` | `hh` | OFF=0x00 / ON=0x7F |
| F8 | FX SELECT (MOBIUS SAW) | — | rotate | — | 5 | NOTE | `44` | `94` | `2C` | `hh` | OFF=0x00 / ON=0x7F |
| F8 | FX SELECT (MOBIUS TRI) | — | rotate | — | 5 | NOTE | `45` | `94` | `2D` | `hh` | OFF=0x00 / ON=0x7F |
| F9 | CH SELECT (CH1) | — | rotate | — | 5 | NOTE | `16` | `94` | `10` | `hh` | OFF=0x00 / ON=0x7F |
| F9 | CH SELECT (CH2) | — | rotate | — | 5 | NOTE | `17` | `94` | `11` | `hh` | OFF=0x00 / ON=0x7F |
| F9 | CH SELECT (CH3) | — | rotate | — | 5 | NOTE | `18` | `94` | `12` | `hh` | OFF=0x00 / ON=0x7F |
| F9 | CH SELECT (CH4) | — | rotate | — | 5 | NOTE | `19` | `94` | `13` | `hh` | OFF=0x00 / ON=0x7F |
| F9 | CH SELECT (MASTER) | — | rotate | — | 5 | NOTE | `20` | `94` | `14` | `hh` | OFF=0x00 / ON=0x7F |
| F9 | CH SELECT (MIC) | — | rotate | — | 5 | NOTE | `21` | `94` | `15` | `hh` | OFF=0x00 / ON=0x7F |
| F9 | CH SELECT (SAMPLER) | — | rotate | — | 5 | NOTE | `22` | `94` | `16` | `hh` | OFF=0x00 / ON=0x7F |
| F10 | LEVEL/DEPTH | — | rotate | — | 5 | CC | `2 34` | `B4` | `02 22` | `MSB LSB` | 0–16383。反時計回り端=Min / 時計回り端=Max |
| F11 | FX ON/OFF | — | press | — | 5 | NOTE | `71` | `94` | `47` | `hh` | OFF=0x00 / ON=0x7F |
| F11 | FX ON/OFF | +SHIFT | press | — | 5 | NOTE | `67` | `94` | `43` | `hh` | OFF=0x00 / ON=0x7F |

## BROWSER（ch 7）

ロータリーセレクターは左右それぞれ独立した操作子（`B1-L` / `B1-R`）だが、回転は同じ CC `0x40` を共有する。押し込みだけがデッキ別の Note に分かれ、これが LOAD にあたる（`0x46`=DECK 1, `0x47`=DECK 2, `0x48`=DECK 3, `0x49`=DECK 4）。

| Fig | コントロール | 修飾 | 動作 | 条件 | ch | 種別 | Data 1 (dec) | Status | Data 1 (hex) | Data 2 | 備考 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| B1-L | Rotary Selector | — | rotate | — | 7 | CC | `64` | `B6` | `40` | `hh` | 相対値（前回操作からの差分）。CW: 1 ~ 30 (0x01 ~ 0x1E) / CCW: 127 ~ 98 (0x7F ~ 0x62) |
| B1-L | Rotary Selector | +SHIFT | rotate | — | 7 | CC | `100` | `B6` | `64` | `hh` | 相対値（前回操作からの差分）。CW: 1 ~ 30 (0x01 ~ 0x1E) / CCW: 127 ~ 98 (0x7F ~ 0x62) |
| B1-L | Rotary Selector | — | press | DECK 1 | 7 | NOTE | `70` | `96` | `46` | `hh` | OFF=0x00 / ON=0x7F |
| B1-L | Rotary Selector | +SHIFT | press | DECK 1 | 7 | NOTE | `93` | `96` | `5D` | `hh` | OFF=0x00 / ON=0x7F |
| B1-L | Rotary Selector | — | press | DECK 3 | 7 | NOTE | `72` | `96` | `48` | `hh` | OFF=0x00 / ON=0x7F |
| B1-L | Rotary Selector | +SHIFT | press | DECK 3 | 7 | NOTE | `94` | `96` | `5E` | `hh` | OFF=0x00 / ON=0x7F |
| B1-R | Rotary Selector | — | rotate | — | 7 | CC | `64` | `B6` | `40` | `hh` | 相対値（前回操作からの差分）。CW: 1 ~ 30 (0x01 ~ 0x1E) / CCW: 127 ~ 98 (0x7F ~ 0x62) |
| B1-R | Rotary Selector | +SHIFT | rotate | — | 7 | CC | `100` | `B6` | `64` | `hh` | 相対値（前回操作からの差分）。CW: 1 ~ 30 (0x01 ~ 0x1E) / CCW: 127 ~ 98 (0x7F ~ 0x62) |
| B1-R | Rotary Selector | — | press | DECK 2 | 7 | NOTE | `71` | `96` | `47` | `hh` | OFF=0x00 / ON=0x7F |
| B1-R | Rotary Selector | +SHIFT | press | DECK 2 | 7 | NOTE | `109` | `96` | `6D` | `hh` | OFF=0x00 / ON=0x7F |
| B1-R | Rotary Selector | — | press | DECK 4 | 7 | NOTE | `73` | `96` | `49` | `hh` | OFF=0x00 / ON=0x7F |
| B1-R | Rotary Selector | +SHIFT | press | DECK 4 | 7 | NOTE | `111` | `96` | `6F` | `hh` | OFF=0x00 / ON=0x7F |
| B2-L B2-R | BACK | — | press | — | 7 | NOTE | `101` | `96` | `65` | `hh` | OFF=0x00 / ON=0x7F |
| B2-L B2-R | BACK | +SHIFT | press | — | 7 | NOTE | `102` | `96` | `66` | `hh` | OFF=0x00 / ON=0x7F |
| B3-L B3-R | VIEW | — | press | — | 7 | NOTE | `122` | `96` | `7A` | `hh` | OFF=0x00 / ON=0x7F |
| B3-L B3-R | VIEW | LONG | press | — | 7 | NOTE | `103` | `96` | `67` | `hh` | OFF=0x00 / ON=0x7F |
| B3-L B3-R | VIEW | +SHIFT | press | — | 7 | NOTE | `104` | `96` | `68` | `hh` | OFF=0x00 / ON=0x7F |

## PERFORMANCE PAD（ch 8–15）

パッドは Data 1 だけでモード・ページ・スロットが決まる。**`mode = note >> 4`、`slot = note & 0x0F`（うち上位ビットが PAGE、下位3ビットがパッド番号）**。SHIFT の有無はチャンネルで分かれるので Note 番号は同じ。

| パッドモード | PAGE | PAD 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| HOT CUE mode | 1 | `00` | `01` | `02` | `03` | `04` | `05` | `06` | `07` |
| HOT CUE mode | 2 | `08` | `09` | `0A` | `0B` | `0C` | `0D` | `0E` | `0F` |
| PAD FX mode 1 | 1 | `10` | `11` | `12` | `13` | `14` | `15` | `16` | `17` |
| PAD FX mode 1 | 2 | `18` | `19` | `1A` | `1B` | `1C` | `1D` | `1E` | `1F` |
| BEAT JUMP mode | 1 | `20` | `21` | `22` | `23` | `24` | `25` | `26` | `27` |
| BEAT JUMP mode | 2 | `28` | `29` | `2A` | `2B` | `2C` | `2D` | `2E` | `2F` |
| SAMPLER mode | 1 | `30` | `31` | `32` | `33` | `34` | `35` | `36` | `37` |
| SAMPLER mode | 2 | `38` | `39` | `3A` | `3B` | `3C` | `3D` | `3E` | `3F` |
| KEYBOARD mode | 1 | `40` | `41` | `42` | `43` | `44` | `45` | `46` | `47` |
| KEYBOARD mode | 2 | `48` | `49` | `4A` | `4B` | `4C` | `4D` | `4E` | `4F` |
| PAD FX mode 2 | 1 | `50` | `51` | `52` | `53` | `54` | `55` | `56` | `57` |
| PAD FX mode 2 | 2 | `58` | `59` | `5A` | `5B` | `5C` | `5D` | `5E` | `5F` |
| BEAT LOOP mode | 1 | `60` | `61` | `62` | `63` | `64` | `65` | `66` | `67` |
| BEAT LOOP mode | 2 | `68` | `69` | `6A` | `6B` | `6C` | `6D` | `6E` | `6F` |
| KEY SHIFT mode | 1 | `70` | `71` | `72` | `73` | `74` | `75` | `76` | `77` |
| KEY SHIFT mode | 2 | `78` | `79` | `7A` | `7B` | `7C` | `7D` | `7E` | `7F` |

### PAD MODE / PAGE ボタン（ch 1–4）

モード切替ボタンとページ切替ボタンはパッドチャンネルではなく**デッキチャンネル**に出る。PAGE ボタンは現在のパッドモードによって Note 番号が変わる。

| Fig | ボタン | 修飾 | 条件 | ch | Data 1 (dec) | Data 1 (hex) |
| --- | --- | --- | --- | --- | --- | --- |
| P9 | HOT CUE | — | — | 1/2/3/4 | `27` | `1B` |
| P9 | HOT CUE | +SHIFT | — | 1/2/3/4 | `105` | `69` |
| P10 | PAD FX | — | — | 1/2/3/4 | `30` | `1E` |
| P10 | PAD FX | +SHIFT | — | 1/2/3/4 | `107` | `6B` |
| P11 | BEAT JUMP | — | — | 1/2/3/4 | `32` | `20` |
| P11 | BEAT JUMP | +SHIFT | — | 1/2/3/4 | `109` | `6D` |
| P12 | SAMPLER | — | — | 1/2/3/4 | `34` | `22` |
| P12 | SAMPLER | +SHIFT | — | 1/2/3/4 | `111` | `6F` |
| P13 | PAGE ◀ (*1) | — | HOT CUE mode | 1/2/3/4 | `36` | `24` |
| P13 | PAGE ◀ (*1) | +SHIFT | HOT CUE mode | 1/2/3/4 | `1` | `01` |
| P13 | PAGE ◀ (*1) | — | PAD FX mode 1 | 1/2/3/4 | `37` | `25` |
| P13 | PAGE ◀ (*1) | +SHIFT | PAD FX mode 1 | 1/2/3/4 | `2` | `02` |
| P13 | PAGE ◀ (*1) | — | BEAT JUMP mode | 1/2/3/4 | `38` | `26` |
| P13 | PAGE ◀ (*1) | +SHIFT | BEAT JUMP mode | 1/2/3/4 | `3` | `03` |
| P13 | PAGE ◀ (*1) | — | SAMPLER mode | 1/2/3/4 | `39` | `27` |
| P13 | PAGE ◀ (*1) | +SHIFT | SAMPLER mode | 1/2/3/4 | `4` | `04` |
| P13 | PAGE ◀ (*1) | — | KEYBOARD mode | 1/2/3/4 | `40` | `28` |
| P13 | PAGE ◀ (*1) | +SHIFT | KEYBOARD mode | 1/2/3/4 | `5` | `05` |
| P13 | PAGE ◀ (*1) | — | PAD FX mode 2 | 1/2/3/4 | `41` | `29` |
| P13 | PAGE ◀ (*1) | +SHIFT | PAD FX mode 2 | 1/2/3/4 | `6` | `06` |
| P13 | PAGE ◀ (*1) | — | BEAT LOOP mode | 1/2/3/4 | `42` | `2A` |
| P13 | PAGE ◀ (*1) | +SHIFT | BEAT LOOP mode | 1/2/3/4 | `7` | `07` |
| P13 | PAGE ◀ (*1) | — | KEY SHIFT mode | 1/2/3/4 | `43` | `2B` |
| P13 | PAGE ◀ (*1) | +SHIFT | KEY SHIFT mode | 1/2/3/4 | `8` | `08` |
| P14 | PAGE ▶ (*1) | — | HOT CUE mode | 1/2/3/4 | `44` | `2C` |
| P14 | PAGE ▶ (*1) | +SHIFT | HOT CUE mode | 1/2/3/4 | `9` | `09` |
| P14 | PAGE ▶ (*1) | — | PAD FX mode 1 | 1/2/3/4 | `45` | `2D` |
| P14 | PAGE ▶ (*1) | +SHIFT | PAD FX mode 1 | 1/2/3/4 | `122` | `7A` |
| P14 | PAGE ▶ (*1) | — | BEAT JUMP mode | 1/2/3/4 | `46` | `2E` |
| P14 | PAGE ▶ (*1) | +SHIFT | BEAT JUMP mode | 1/2/3/4 | `123` | `7B` |
| P14 | PAGE ▶ (*1) | — | SAMPLER mode | 1/2/3/4 | `47` | `2F` |
| P14 | PAGE ▶ (*1) | +SHIFT | SAMPLER mode | 1/2/3/4 | `124` | `7C` |
| P14 | PAGE ▶ (*1) | — | KEYBOARD mode | 1/2/3/4 | `48` | `30` |
| P14 | PAGE ▶ (*1) | +SHIFT | KEYBOARD mode | 1/2/3/4 | `125` | `7D` |
| P14 | PAGE ▶ (*1) | — | PAD FX mode 2 | 1/2/3/4 | `49` | `31` |
| P14 | PAGE ▶ (*1) | +SHIFT | PAD FX mode 2 | 1/2/3/4 | `126` | `7E` |
| P14 | PAGE ▶ (*1) | — | BEAT LOOP mode | 1/2/3/4 | `50` | `32` |
| P14 | PAGE ▶ (*1) | +SHIFT | BEAT LOOP mode | 1/2/3/4 | `127` | `7F` |
| P14 | PAGE ▶ (*1) | — | KEY SHIFT mode | 1/2/3/4 | `51` | `33` |
| P14 | PAGE ▶ (*1) | +SHIFT | KEY SHIFT mode | 1/2/3/4 | `0` | `00` |

## MIDI-OUT 専用（Illumination Control）

ジョグ画面と一部 LED はホストから送るだけの一方向。ステータスは MIDI-OUT 側の値。

| 機能 | 用途 | ch | 種別 | Data 1 (dec) | Status | Data 1 (hex) | Data 2 | 値域 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Current position bar | for JOG display (*2) | 1/2/3/4 | CC | `20 / 52` | `Bn` | `14 / 34` | `MSB / LSB` | Min (MSB:0x00, LSB:0x00) ~ Max (MSB:0x02, LSB:0x67) / 0 ~ 359 [degree] |
| BPM value | for JOG display (*2) | 1/2/3/4 | CC | `21 / 53` | `Bn` | `15 / 35` | `MSB / LSB` | Min (MSB:0x00, LSB:0x00) ~ Max (MSB:0x4E, LSB:0x0F) / BPM: 0.0 ~ 999.9 |
| Playing speed | for JOG display (*2) | 1/2/3/4 | CC | `22 / 54` | `Bn` | `16 / 36` | `MSB / LSB` | Min (MSB:0x00, LSB:0x00) ~ Max (MSB:0x4E, LSB:0x0F) / Playing speed: -100.0% ~ +100.0% |
| Current time (minute) | for JOG display (*2) | 1/2/3/4 | NOTE | `66` | `9n` | `42` | `hh` | 0x00 ~ 0x63 (0~99) |
| Current time (second) | for JOG display (*2) | 1/2/3/4 | NOTE | `67` | `9n` | `43` | `hh` | 0x00 ~ 0x3B (0~59) |
| Time mode | for JOG display (*2) | 1/2/3/4 | NOTE | `68` | `9n` | `44` | `hh` | Elapsed: OFF=0x00 / Remaining: ON=0x7F |
| Cue marker | for JOG display (*2) | 1/2/3/4 | CC | `23 / 55` | `Bn` | `17 / 37` | `MSB / LSB` | Min (MSB:0x00, LSB:0x00) ~ Max (MSB:0x02, LSB:0x67) / 0 ~ 359 [degree] / Hide Cue marker: (MSB:0x7F, LSB:0x7F) |
| Key value | for JOG display (*2) | 1/2/3/4 | NOTE | `73` | `9n` | `49` | `hh` | 0x00~0x18 (*3) |
| Key variation | for JOG display (*2) | 1/2/3/4 | NOTE | `74` | `9n` | `4A` | `hh` | 0x01-0x0C (-12 ~ -1), 0x0D (0), 0x0E~0x19 (+1 ~ +12) |
| Beat Sync Master | for JOG display (*2) | 1/2/3/4 | NOTE | `89` | `9n` | `59` | `hh` | OFF=0x00, ON=0x7F |
| Beat Sync State | for JOG display (*2) | 1/2/3/4 | NOTE | `90` | `9n` | `5A` | `hh` | OFF=0x00, ON=0x7F |
| JOG Ring LED State | for JOG display (*2) | 1/2/3/4 | NOTE | `91` | `9n` | `5B` | `hh` | OFF=0x00, WHITE=0x01 |
| Display/hide information on the jog dial display | for JOG display (*2) | 1/2/3/4 | NOTE | `93` | `9n` | `5D` | `hh` | Display information=0x00, Hide information=0x7F (To hide information, send 0x7F.) |

## KEY 値テーブル（*3）

`Key value`（Note `0x49`）の Data 2 に入れる値。

| Dec | 0 | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 | 11 | 12 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Hex | `00` | `01` | `02` | `03` | `04` | `05` | `06` | `07` | `08` | `09` | `0A` | `0B` | `0C` |
| KEY | --- | C | Am | Db | Bbm | D | Bm | Eb | Cm | E | Dbm | F | Dm |

| Dec | 13 | 14 | 15 | 16 | 17 | 18 | 19 | 20 | 21 | 22 | 23 | 24 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Hex | `0D` | `0E` | `0F` | `10` | `11` | `12` | `13` | `14` | `15` | `16` | `17` | `18` |
| KEY | F# | Ebm | G | Em | Ab | Fm | A | F#m | Bb | Gm | B | Abm |

`Key variation`（Note `0x4A`）は別枠で、`0x01`–`0x0C` が −12〜−1、`0x0D` が 0、`0x0E`–`0x19` が +1〜+12。

## 公式表に載っていないメッセージ

| メッセージ | 用途 | 根拠 |
| --- | --- | --- |
| `9F 09 7F` | PC APP CONNECT。ホストがこれを送ると本体が現在のフェーダー・つまみ位置を送り返す | Mixxx wiki。公式表はチャンネル16に触れていない |
| レベルメーター | 公式表に出力メッセージが無い。本体図では `M21`（MASTER）/ `M22-1`〜`M22-4`（各 CH）としてメーターが描かれているが、メッセージ表に対応する行が存在しない | 公式表の欠落 |
| 曲名・アートワーク・波形のジョグ画面転送 | 公式表の MIDI-OUT は数値・LED のみ。画像転送は MIDI では規定されていない | 公式表 |

## 原典の不整合

- **DECK SELECT の Status** — `D6-L` は「MIDI Channel 1（DECK 3 へ切替）」「MIDI Channel 3（DECK 1 へ切替）」の2行とも Status が `92` と印字されている。チャンネル1なら `90` のはずで、公式表の中で唯一つじつまが合わない。`D6-R` も同様に2行とも `93`。実機で確定させるには `native/ddj-1000-diagnostics` で生バイトを取るのが早い。
- **`FX SELECT (LOW CUT`** — 原典のセル内で文字列が切れている。BEAT FX セレクターの刻印は "LOW CUT ECHO"。
- **`SAMPER`** — 原典の誤記。正しくは SAMPLER。
- **`SLPI ROLL`** — 原典の誤記。正しくは SLIP ROLL。
- **矢印** — 原典が私用領域のグリフを使っているため、`SEARCH ◀◀ / ▶▶`、`BEAT ◀ / ▶`、`PAGE ◀ / ▶` は Fig. 番号（左が小さい方）から補った。

## 既存実装との突き合わせ

`src/services/midi/ddj1000.ts` のデコーダー／フィードバックを上の一覧と照合した結果。一致している箇所は省く（パッドの `note>>4` = モード・`note&0x0F` = ページ×スロット、14bit CC 群、LOAD の ch7 `0x46`–`0x49`、CRF ASSIGN、PAD MODE ボタン、ジョグ画面出力の `0x14`/`0x15`/`0x16`・`0x42`/`0x43`/`0x44`・`0x5A`/`0x5B`/`0x5D` はいずれも公式表どおり）。

| 実装 | 公式表 |
| --- | --- |
| `0x12: loopHalf` / `0x13: loopDouble`（デッキ ch） | デッキ ch に該当 Note なし。DDJ-1000 に LOOP 1/2・×2 ボタンは無く、`D10` IN ADJUST / `D11` OUT ADJUST / `D12` 4 BEAT LOOP/EXIT のみ |
| `0x3A: vinylState`（デッキ ch） | 該当 Note なし。VINYL は SHIFT+SLIP の `0x17` |
| `0x3C: deckSelect`（デッキ ch） | 該当 Note なし。DECK SELECT は `0x72`（Status `92`/`93`）で、実装が併記している `0x72` の方が正しい |
| `0x23` → `nudge` | `0x23` は VINYL OFF 時のプラッター上面。側面（ナッジ）は `0x21`。VINYL ON 時の `0x22` と対になる |
| `0x29`（SEARCH+プラッター）/ `0x1F`（SHIFT+プラッター）未処理 | 公式表にあり |
| フィードバック `B0+ch 02 vv`（レベルメーター） | 公式表にレベルメーター出力は無い。ch5 の CC 2/34 は BEAT FX LEVEL/DEPTH で、デッキ ch の CC 2 は入出力とも未定義 |

### 実装への反映

- デッキNote `0x12` / `0x13` / `0x3A` / `0x3C` はデコーダーから削除済み。
- ジョグCCは6種類を区別。`0x22` / `0x23` は上面のVINYL ON/OFF、`0x21` は側面、`0x26` はSHIFT＋側面、`0x29` はSEARCH＋上面、`0x1F` はSHIFT＋上面。アクションに操作面と修飾情報を保持する。VINYL OFFとSEARCHでは保持中のスクラッチを解除する。
- BPM／再生速度の表示出力を原典の最大値9999に制限し、`0x59`のSYNC MASTER表示を追加。
- レベルメーターのデッキCC `0x02` は未定義である旨をコードに明記し、実機での目視確認まで現行出力を保持。BEAT FXのch5へ変更しない。
- DECK SELECT `0x72` は現行処理を保持。`native/ddj-1000-diagnostics` でDDJ-1000のsourceを指定して45秒記録したが、生バイトは0件だったため原典の矛盾を解決したとは扱わない。
- 公式JSONを読むデコーダー回帰テスト、全パッドチャンネルの2ページ分、表示範囲、VINYL OFF／SEARCH中のスクラッチ解除を検査。Node側21テストと既存ネイティブ統合テストが成功。統合テストの音声出力はBlackHole 2chであり、実機LEDの検証を代替しない。
