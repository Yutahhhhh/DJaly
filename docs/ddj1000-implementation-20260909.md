# DDJ-1000 実装と検証 — 2026-09-09

[機能監査](ddj1000-feature-audit-20260909.md)は**実装前**の記録。本書はその後に実施した実装・修正・検証の記録で、監査表の達成状況を上書きするものではない。実機への送信、アプリ再起動、commit / push / release は行っていない。

## 0. 検証環境の制約（結果を読む前に）

**この機械では現在、仮想 CoreAudio デバイスが一切開けない。** `BlackHole 2ch` / `MJRecorder Device` / `ZoomAudioDevice` / `Microsoft Teams Audio` / `DJ Stream` / `rekordbox直結` のいずれも `Pa_OpenStream()` で無限に止まり、`Opening stream with id N` の次のログが出ない。物理出力（`MacBook Airのスピーカー`）だけが正常に開く。

これは Djaly のコードが原因ではない。**変更を一切加えていない `first-fx.test.mjs`（既存の合格テスト）も BlackHole では同じ位置でハングする**ことを確認済み。したがって録音を伴うテストはすべて次の指定で実行した。

```bash
DJALY_MIXXX_OUTPUT_DEVICE="MacBook Airのスピーカー" node --test <file>
```

録音は Mixxx の RecordingManager がエンジン内部のマスターバスを取るため、出力デバイスの選択は測定結果に影響しない（デバイスはコールバックを回すためだけに必要）。ただし**テスト中は実際にスピーカーからテストトーンが鳴る**。仮想デバイスが復旧すれば `DJALY_MIXXX_OUTPUT_DEVICE` の指定は不要に戻る。

原因は未特定。`coreaudiod` 側の状態と思われる。アプリ（`pnpm tauri dev`、PID 15258 → エンジンホスト PID 20108、04:26 起動）が動いたままなので、その関与も否定できていない。依頼どおりアプリは落としていない。

## 1. 最優先だった BEAT FX 無音 — 原因特定と修正

### 事実

同一プロセス・同一デッキ・同一 echo で比較した測定（無音区間の最小 RMS）:

| 操作 | 修正前 | 修正後 |
|---|---:|---:|
| FX なし | 0.00 | 0.00 |
| **BEAT FX echo（第5チェーン）** | **0.00** | **739.27** |
| BEAT FX off | 0.00 | 0.00 |
| PAD FX echo（第1チェーン、比較用） | 811.65 | 711.68 |

修正前、`state.snapshot` の `mixer.beatFx` は**正常値と完全に一致**していた（`processor: org.mixxx.effects.echo` / `slotEnabled: 1` / `nativeEnabled: 1` / `routes: ["[Channel1]"]` / `send_amount: 1` / `delay_time: 0.5`）。表示が正しいのに音だけが出ない状態だった。

### 原因

`EffectSlot::setEnabled()` はエフェクトの有効フラグを**オーディオスレッドへ伝えない**。

- スロットの有効状態が `SET_EFFECT_PARAMETERS` としてエンジンへ送られるのは、`EffectSlot::updateEngineState()` を通る 2 経路だけ（`upstream/src/effects/effectslot.cpp`）。
  1. `m_pControlEnabled` の `valueChanged` ハンドラ
  2. `loadEffectInner()` の末尾（このとき `m_pControlEnabled->toBool()` を**その時点の値で標本化**する）
- `setEnabled()` は `m_pControlEnabled->set(enabled)` を呼ぶ。`ControlObject::set(double)` は自分自身を sender として渡し、`ControlObject::privateValueChanged()` は `pSender != this` のときしか `valueChanged` を発火しない（`upstream/src/control/controlobject.cpp:49`）。**自分で書いた値では自分のハンドラが動かない。**
- つまり `setEnabled()` 単独ではエンジンに何も届かない。エンジン側は `EffectEnableState::Disabled` のままで、`EffectProcessorImpl::process()` は入力をそのまま出力へコピーして戻る（＝完全にドライ、テールなし）。

**PAD FX が動いていたのは偶然。** `deck.load` が `disableFx()` を呼んで `fxLoaded_` を落とすため、曲を読んだ後の最初の PAD FX 操作では必ずエフェクトが再ロードされ、その `loadEffectInner()` 末尾の `updateEngineState()` が、初期化時に 1 のまま残っていた CO 値を拾ってエンジンへ届けていた。BEAT FX は effect が変わらない限り再ロードしないので、この経路に一度も乗らなかった。

### 修正

`native/mixxx-engine-host/src/beat_fx.h` — 有効状態を**ロードより前に**、かつ静的セッター経由で publish する。静的 `ControlObject::set(ConfigKey, double)` は sender に `nullptr` を渡すため `valueChanged` が正しく発火し、ロード経路（標本化）と非ロード経路（シグナル）の両方で意図した値が伝わる。

```cpp
ControlObject::set(ConfigKey(slotGroup(), "enabled"), enabled_ ? 1 : 0);
if (effect_ != effect || !getEffectSlot(0)->isLoaded()) { /* load */ }
```

テストは一切弱めていない。`beat-fx-audio.test.mjs` は無改変のまま合格する。

### 併せて否定した仮説

**`EffectsMessenger` の初期化 FIFO（2048 件）溢れではない。** 引き継ぎで最有力とされていたので実測した。音声開始前に `effects_->getEngineEffectsManager()->onCallbackStart()` を呼んで FIFO を drain する版をビルドして比較したが、**BEAT FX は無音のまま**だった。静的にも、64 サンプラー・EQ/Quick チェーン・5 本の Standard チェーンを合計しても送信数は数百件で 2048 には遠い。この仮説は根拠なしとして採用しない。検証用のコードは残していない。

## 2. 同じ欠陥が SOUND COLOR FX にもあった（新規発見・修正）

`colorFx()` も `slot->setEnabled()` を使っていた。**ノブを中央（0）に戻してから別の Color FX を選ぶと、そのエフェクトは完全に無音になる。**

修正前後を実測（同じプローブ、修正を戻したバイナリと比較）:

| 手順 | 修正前 | 修正後 |
|---|---:|---:|
| FILTER を -0.9（LPF）→ 8kHz 帯 | 1100 → 0（動作） | 1100 → 0（動作） |
| ノブを 0 に戻す | ニュートラル | ニュートラル |
| **その状態で D-ECHO 0.9** | **最小 RMS 0.00（無音）** | **最小 RMS 1586.99** |
| WHITE NOISE 0.8 | 5439.79 | 5450.81 |
| 0 に戻す | 0.00 | 0.00 |

FILTER が無事だったのは、Quick チェーンが構築時に `setEnabled(true)` を通しており、その値が effects.xml 由来の初回ロードで標本化されていたため。ノブを 0 にした時点で CO が 0 になり、以降にロードされるエフェクトがすべて巻き添えになる、という並びだった。

## 3. PAD FX の同型の潜在バグを明示的に解消

`fx()` の `chain->getEffectSlot(0)->setEnabled(true)` も同じ性質で、**「曲ロードが再ロードを強制する」という副作用にたまたま依存していた**。同じ静的セッター方式に置き換え、依存を明示した。挙動は変わらず、保護対象の `first-fx.test.mjs` を含め全テストが合格する。

## 4. その他の実装・修正

| 対象 | 内容 |
|---|---|
| `src/services/midi/ddj1000-runtime.ts` | ネイティブ BEAT FX の **MIX ノブ coalescing を追加**。従来は CC 1 通ごとに `mixer.beatfx.set` を積み、ノブを回すとキューが無制限に伸びていた。PAD FX 側と同じ「1 本だけ in-flight、最新値だけ保持」に統一。20 メッセージのスイープが 1 リクエストになり、最後に置いた位置が必ず適用される。 |
| `src/services/midi/ddj1000-runtime.ts` | **`loopAdjust` / `loopIn` に track identity guard を追加**。従来はデッキに紐づくだけで、IN/OUT 調整モードや保持中の IN 位置が**次にロードした曲へそのまま持ち越されていた**。他のジェスチャ状態（`jogs` / `bends` / `cuePreview` 等）と同じ `{session, track}` 方式に揃え、読み出し時に検証する `held()` を追加。 |
| `src/types/dj-engine.ts` | `BeatFxState` を型として切り出し。`pnpm build` が `TS2683: 'this' implicitly has type 'any'`（`typeof this.nativeFx` を入れ子アロー関数の型位置で使用）で**失敗していたのを修正**。 |
| `native/mixxx-engine-host/tests/ddj1000.test.mjs` | scratch 解放の待ちが固定 100ms でレースしていた（3 回中 2 回失敗）。実測すると解放自体は常に届いており、`reset()` が await しない dispatch であることとエンジンのレート ramp で **100〜130ms** かかる。アサーション（`scratching === false`）はそのままに、固定待ちを既存の `until` によるポーリングへ置換。4/4 で安定。 |

## 5. 追加したテスト

| ファイル | 内容 |
|---|---|
| `native/mixxx-engine-host/tests/sampler-audio.test.mjs` | 既存 `sampler.test.mjs` は無音 fixture なので「playing と報告するだけのパッド」と「実際に鳴るパッド」を区別できない。マスターバスを録音し、パッド発火で可聴・ロードだけでは無音・`stopAll` で停止・ゲイン差が音量差として出る・バンク指定再生・`session.hello` で停止、を検証。PFL はキューバスが無い環境で `unsupported_operation` を返すことを確認。3/3 で安定。 |
| `native/mixxx-engine-host/tests/colorfx-audio.test.mjs` | 上記 2 の回帰を固定。FILTER が 8kHz を実際に削ること、**ノブ中央で Color FX を切り替えても音が出ること**、0 に戻すとテールが残らないこと。 |
| `native/dj-engine-host/tests-node/ddj1000-gesture-state.test.ts` | MIX coalescing と loop ジェスチャの track identity guard の回帰。**mutation test で有効性を確認済み**（修正を戻すと 4 件中 3 件が落ち、戻し後はファイルが byte-identical に復元されることを sha256 で確認）。 |

保護対象の `native/dj-engine-host/tests-node/ddj1000.test.ts` と `ddj1000-display.test.ts` は**変更していない**。

## 6. 検証結果（最終バイナリ）

| 対象 | 結果 |
|---|---|
| `native/mixxx-engine-host/tests/` 9 ファイル（beat-fx-audio / first-fx / colorfx-audio / sampler-audio / sampler / ddj1000 / dj-controls / beatgrid / negative-position） | 全 10 件 PASS |
| `native/dj-engine-host/tests-node/*.test.ts` 全件 | 102 件 PASS |
| `pnpm build` | PASS |
| `backend/tests/test_performance_metadata.py` | 16 件 PASS |
| `native/ddj-1000-diagnostics` `cargo test` | 3 件 PASS |
| upstream Mixxx | `3ebac449`（2.5.6）、`git status` clean・無改変 |

ローカル staging は `bash native/mixxx-engine-host/scripts/stage-macos.sh` で実施済み。署名検証まで通り、**staging 済みバンドルのバイナリで beat-fx-audio / colorfx-audio / sampler-audio / first-fx を再実行して合格**を確認した。

**ただしアプリにはまだ反映されていない。** 起動中のアプリ（PID 15258）は 04:26 に起動したエンジンホスト（PID 20108）を掴んだままで、これは古いバイナリ。staging はディレクトリの原子的入れ替えなので走行中プロセスには影響しない。**新機能を実機で試すにはアプリの再起動が必要。**依頼どおり自動では落としていない。

## 7. 未実装・未検証（今回やっていないこと）

### 機能として未着手

- **BEAT FX 14 種のうち 6 種のみ対応**（echo / reverb / tremolo / flanger / phaser / pitchshift）。残り 8 種は明示的にエラーを返す。「互換 FX で補完してよいか、rekordbox と同音でなければならないか」の質問に**回答がまだ無い**ため、独自 FX を同じ音として提供する変更は入れていない。現状の「黙って代替せずエラーにする」が、回答が来るまでの安全側。
- `fxAuto` / `fxTap`（`0x66` / `0x6b`）はデコードのみ。runtime に処理なし。
- SHIFT+4BEAT の ActiveLoop、SEARCH / TRACK SEARCH の押しっぱなし反復、SHIFT ジョグでのビートグリッド編集。
- KEYBOARD / KEY SHIFT の公式 5 ページとの差分、PAGE / モード LED、MEMORY パッドの UI、編集可能な PAD FX プリセット。
- HID の非アートワーク項目（LOOP / KEY 等）の状態反映。`src-tauri/src/dj_engine/jog_display.rs` とアートワーク周辺は別作業者の領域として触っていない。

### 実機が必要

- **DECK SELECT `0x72`**: 公式表内で status が矛盾したまま。生バイトが取れていないので切替先を確定できず、変更していない。
- **レベルメーター CC `0x02`**: 公式表に定義がない。実機未検証のため既存出力を残している。
- **PFL / キューバス**: `DDJ-1000` を 4ch で開いたときだけ有効。今回は物理スピーカー出力で検証したため、この分岐は未実行。
- LED / 本体表示の同期は、MIDI 出力コードの有無と実際の表示が別問題であり、実機確認が要る。

### 環境起因で保留

- 仮想オーディオデバイスが開けない件（第 0 節）。復旧後に `DJALY_MIXXX_OUTPUT_DEVICE` 指定なしで全録音テストを再実行して、デバイス非依存であることを確認するのが望ましい。

## 8. 補足: scratch 解放レイテンシ

`ddj1000.test.mjs` の調査中に実測した値として、`runtime.reset()` からスナップショットの `scratching` が false になるまで **100〜130ms**。解放コマンド自体は同期的に書き出されており、内訳はエンジン側のレート ramp とスナップショット更新。機能上の取りこぼしではないが、ジョグから手を離した際の体感に関わる数値なので記録しておく。
