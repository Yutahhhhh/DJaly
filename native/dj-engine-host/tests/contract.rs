//! プロトコル契約テスト（インプロセス）。
//!
//! 実ファイル・実 DB・実音声を一切使わず、固定のフィクスチャだけで
//! ライフサイクル / 非同期ロード / リビジョン / 失効 ID / 異常入力を検証する。

use dj_engine_host::{Engine, EngineConfig, Runtime};
use serde_json::{json, Value};

const TRACK_DURATION_MS: f64 = 240_000.0;

fn config(deterministic: bool) -> EngineConfig {
    EngineConfig {
        engine_id: "eng-test".to_string(),
        version: "test".to_string(),
        implementation: "simulator".to_string(),
        deterministic,
        load_latency_ms: 100.0,
        position_interval_ms: 50.0,
        meters_interval_ms: 100.0,
    }
}

fn new_runtime() -> Runtime {
    Runtime::new(Engine::new(config(true)))
}

fn send(runtime: &mut Runtime, command: Value) -> Vec<Value> {
    runtime
        .handle_line(&command.to_string())
        .iter()
        .map(|message| serde_json::to_value(message).expect("メッセージを直列化できること"))
        .collect()
}

/// フィクスチャの曲記述子。実ライブラリのファイルは参照しない。
fn fixture_track(track_id: &str) -> Value {
    json!({
        "trackId": track_id,
        "path": "/fixtures/does-not-need-to-exist.wav",
        "title": "Fixture Track",
        "artist": "Fixture Artist",
        "durationMs": TRACK_DURATION_MS,
        "bpm": 124.0,
        "sampleRateHz": 44100,
        "channels": 2,
        "beatgridOffsetMs": 0.0
    })
}

struct Session {
    engine_id: String,
    session_id: String,
    next_id: u64,
}

impl Session {
    fn command(&mut self, op: &str, params: Value) -> Value {
        let id = self.next_id;
        self.next_id += 1;
        json!({
            "protocol": 1,
            "kind": "command",
            "id": id,
            "sessionId": self.session_id,
            "engineId": self.engine_id,
            "op": op,
            "params": params,
        })
    }
}

fn hello(runtime: &mut Runtime, command_id: u64) -> (Session, Vec<Value>) {
    let messages = send(
        runtime,
        json!({
            "protocol": 1,
            "kind": "command",
            "id": command_id,
            "op": "session.hello",
            "params": { "clientName": "contract-test" },
        }),
    );
    let greeting = messages.first().expect("hello の応答があること").clone();
    assert_eq!(greeting["kind"], "hello");
    let session = Session {
        engine_id: greeting["engineId"].as_str().unwrap().to_string(),
        session_id: greeting["sessionId"].as_str().unwrap().to_string(),
        next_id: command_id + 1,
    };
    (session, messages)
}

fn find(messages: &[Value], kind: &str) -> Option<Value> {
    messages
        .iter()
        .find(|message| message["kind"] == kind)
        .cloned()
}

fn find_event(messages: &[Value], event: &str) -> Option<Value> {
    messages
        .iter()
        .find(|message| message["kind"] == "event" && message["event"] == event)
        .cloned()
}

fn expect_result(messages: &[Value]) -> Value {
    match find(messages, "result") {
        Some(value) => value,
        None => panic!("result を期待しましたが得られませんでした: {messages:?}"),
    }
}

fn expect_error_code(messages: &[Value], code: &str) -> Value {
    let error = match find(messages, "error") {
        Some(value) => value,
        None => panic!("error を期待しましたが得られませんでした: {messages:?}"),
    };
    assert_eq!(error["error"]["code"], code, "エラーコードが一致しません");
    error
}

/// 曲をロードし、ロード完了まで時間を進める。
fn load_ready(runtime: &mut Runtime, session: &mut Session, deck: &str, track_id: &str) {
    let command = session.command(
        "deck.load",
        json!({ "deck": deck, "track": fixture_track(track_id) }),
    );
    let messages = send(runtime, command);
    assert_eq!(expect_result(&messages)["data"]["accepted"], true);

    let advance = session.command("sim.advanceTime", json!({ "ms": 150 }));
    let messages = send(runtime, advance);
    assert!(
        find_event(&messages, "deck.loaded").is_some(),
        "deck.loaded が発火すること: {messages:?}"
    );
}

// ---------------------------------------------------------------- ハンドシェイク

#[test]
fn hello_reports_identity_protocol_range_and_simulated_flag() {
    let mut runtime = new_runtime();
    let (_session, messages) = hello(&mut runtime, 1);
    let greeting = &messages[0];

    assert_eq!(greeting["protocol"], 1);
    assert_eq!(greeting["id"], 1);
    assert_eq!(greeting["engineId"], "eng-test");
    assert_eq!(greeting["protocolVersions"]["min"], 1);
    assert_eq!(greeting["protocolVersions"]["max"], 1);
    // 音を出していないことをエンジン自身が申告する。
    assert_eq!(greeting["engine"]["simulated"], true);
    assert_eq!(greeting["engine"]["implementation"], "simulator");
    assert_eq!(greeting["engine"]["decks"], json!(["A", "B"]));
}

#[test]
fn commands_before_hello_are_rejected() {
    let mut runtime = new_runtime();
    let messages = send(
        &mut runtime,
        json!({ "protocol": 1, "id": 1, "op": "state.snapshot" }),
    );
    expect_error_code(&messages, "session_required");
}

// ---------------------------------------------------------------- スナップショット

#[test]
fn snapshot_exposes_two_decks_mixer_audio_and_revision() {
    let mut runtime = new_runtime();
    let (mut session, _) = hello(&mut runtime, 1);

    let command = session.command("state.snapshot", json!({}));
    let messages = send(&mut runtime, command);
    let snapshot = &expect_result(&messages)["data"];

    assert_eq!(snapshot["decks"]["A"]["status"], "empty");
    assert_eq!(snapshot["decks"]["B"]["status"], "empty");
    assert_eq!(snapshot["decks"]["A"]["deck"], "A");
    assert_eq!(snapshot["mixer"]["crossfader"], 0.0);
    assert_eq!(snapshot["mixer"]["channels"]["A"]["gain"], 1.0);
    // シミュレータは音声デバイスを開かない。
    assert_eq!(snapshot["audio"]["applied"], false);
    assert_eq!(snapshot["rev"], 0);
}

#[test]
fn revision_increases_monotonically_on_every_mutation() {
    let mut runtime = new_runtime();
    let (mut session, _) = hello(&mut runtime, 1);

    let mut previous = 0u64;
    for gain in [0.2_f64, 0.4, 0.6] {
        let command = session.command("mixer.channel.gain", json!({ "deck": "A", "gain": gain }));
        let messages = send(&mut runtime, command);
        let rev = expect_result(&messages)["rev"].as_u64().unwrap();
        assert!(
            rev > previous,
            "rev が単調増加すること: {previous} -> {rev}"
        );
        previous = rev;
    }

    // 読み取り専用の操作は rev を進めない。
    let command = session.command("state.snapshot", json!({}));
    let messages = send(&mut runtime, command);
    assert_eq!(expect_result(&messages)["rev"].as_u64().unwrap(), previous);
}

// ---------------------------------------------------------------- 非同期ロード

#[test]
fn load_is_asynchronous_and_reports_ready_only_after_latency() {
    let mut runtime = new_runtime();
    let (mut session, _) = hello(&mut runtime, 1);

    let command = session.command(
        "deck.load",
        json!({
            "deck": "A",
            "track": fixture_track("t-1"),
            "simulateLoadLatencyMs": 100
        }),
    );
    let messages = send(&mut runtime, command);
    let result = expect_result(&messages);
    assert_eq!(result["data"]["accepted"], true);
    assert_eq!(result["data"]["deck"], "A");
    let state = find_event(&messages, "deck.state").expect("deck.state が来ること");
    assert_eq!(state["data"]["status"], "loading");

    // 所要時間未満ではまだ完了しない。
    let advance = session.command("sim.advanceTime", json!({ "ms": 60 }));
    let messages = send(&mut runtime, advance);
    assert!(find_event(&messages, "deck.loaded").is_none());

    let advance = session.command("sim.advanceTime", json!({ "ms": 60 }));
    let messages = send(&mut runtime, advance);
    let loaded = find_event(&messages, "deck.loaded").expect("deck.loaded が来ること");
    assert_eq!(loaded["data"]["track"]["trackId"], "t-1");
    let state = find_event(&messages, "deck.state").expect("deck.state が来ること");
    assert_eq!(state["data"]["status"], "ready");
}

#[test]
fn load_failure_path_reports_structured_failure() {
    let mut runtime = new_runtime();
    let (mut session, _) = hello(&mut runtime, 1);

    let command = session.command(
        "deck.load",
        json!({
            "deck": "A",
            "track": fixture_track("t-broken"),
            "simulateLoadFailure": true
        }),
    );
    send(&mut runtime, command);

    let advance = session.command("sim.advanceTime", json!({ "ms": 200 }));
    let messages = send(&mut runtime, advance);
    let failed = find_event(&messages, "deck.load.failed").expect("deck.load.failed が来ること");
    assert_eq!(failed["data"]["error"]["code"], "load_failed");

    // 失敗後のデッキは再生できない。
    let command = session.command("deck.play", json!({ "deck": "A" }));
    let messages = send(&mut runtime, command);
    expect_error_code(&messages, "no_track_loaded");
}

#[test]
fn transport_on_loading_deck_is_retryable_error() {
    let mut runtime = new_runtime();
    let (mut session, _) = hello(&mut runtime, 1);

    let command = session.command(
        "deck.load",
        json!({ "deck": "B", "track": fixture_track("t-2") }),
    );
    send(&mut runtime, command);

    let command = session.command("deck.play", json!({ "deck": "B" }));
    let messages = send(&mut runtime, command);
    let error = expect_error_code(&messages, "track_not_ready");
    assert_eq!(error["error"]["retryable"], true);
}

// ---------------------------------------------------------------- 再生

#[test]
fn playback_advances_simulated_position_and_emits_position_events() {
    let mut runtime = new_runtime();
    let (mut session, _) = hello(&mut runtime, 1);
    load_ready(&mut runtime, &mut session, "A", "t-1");

    let command = session.command("deck.play", json!({ "deck": "A" }));
    let messages = send(&mut runtime, command);
    let state = find_event(&messages, "deck.state").expect("deck.state が来ること");
    assert_eq!(state["data"]["status"], "playing");

    let advance = session.command("sim.advanceTime", json!({ "ms": 1000 }));
    let messages = send(&mut runtime, advance);
    let position = find_event(&messages, "deck.position").expect("deck.position が来ること");
    let position_ms = position["data"]["decks"]["A"]["positionMs"]
        .as_f64()
        .unwrap();
    assert!(
        (position_ms - 1000.0).abs() < 1e-6,
        "1 秒進めたら 1000ms になること: {position_ms}"
    );
    // ミリ秒とフレームの対応が境界で一致していること。
    let frames = position["data"]["decks"]["A"]["positionFrames"]
        .as_u64()
        .unwrap();
    assert_eq!(frames, 44_100);
}

#[test]
fn tempo_change_scales_position_progression_and_effective_bpm() {
    let mut runtime = new_runtime();
    let (mut session, _) = hello(&mut runtime, 1);
    load_ready(&mut runtime, &mut session, "A", "t-1");

    let command = session.command("deck.tempo.set", json!({ "deck": "A", "rate": 1.5 }));
    let messages = send(&mut runtime, command);
    let state = find_event(&messages, "deck.state").expect("deck.state が来ること");
    assert_eq!(state["data"]["effectiveBpm"], 186.0);

    let command = session.command("deck.play", json!({ "deck": "A" }));
    send(&mut runtime, command);
    let advance = session.command("sim.advanceTime", json!({ "ms": 1000 }));
    let messages = send(&mut runtime, advance);
    let position_ms = find_event(&messages, "deck.position").expect("deck.position")["data"]
        ["decks"]["A"]["positionMs"]
        .as_f64()
        .unwrap();
    assert!(
        (position_ms - 1500.0).abs() < 1e-6,
        "得られた値: {position_ms}"
    );
}

#[test]
fn enabled_loop_wraps_the_playhead() {
    let mut runtime = new_runtime();
    let (mut session, _) = hello(&mut runtime, 1);
    load_ready(&mut runtime, &mut session, "A", "t-1");

    let command = session.command(
        "deck.loop.set",
        json!({ "deck": "A", "startMs": 1000, "endMs": 2000 }),
    );
    send(&mut runtime, command);
    let command = session.command("deck.seek", json!({ "deck": "A", "positionMs": 1900 }));
    send(&mut runtime, command);
    let command = session.command("deck.play", json!({ "deck": "A" }));
    send(&mut runtime, command);

    let advance = session.command("sim.advanceTime", json!({ "ms": 200 }));
    let messages = send(&mut runtime, advance);
    let position_ms = find_event(&messages, "deck.position").expect("deck.position")["data"]
        ["decks"]["A"]["positionMs"]
        .as_f64()
        .unwrap();
    assert!(
        (position_ms - 1100.0).abs() < 1e-6,
        "得られた値: {position_ms}"
    );
}

#[test]
fn hot_cue_set_and_jump_round_trip() {
    let mut runtime = new_runtime();
    let (mut session, _) = hello(&mut runtime, 1);
    load_ready(&mut runtime, &mut session, "A", "t-1");

    let command = session.command(
        "deck.hotcue.set",
        json!({ "deck": "A", "index": 2, "positionMs": 30_000 }),
    );
    send(&mut runtime, command);
    let command = session.command("deck.seek", json!({ "deck": "A", "positionMs": 0 }));
    send(&mut runtime, command);
    let command = session.command("deck.hotcue.jump", json!({ "deck": "A", "index": 2 }));
    let messages = send(&mut runtime, command);
    assert_eq!(expect_result(&messages)["data"]["positionMs"], 30_000.0);

    let command = session.command("deck.hotcue.jump", json!({ "deck": "A", "index": 5 }));
    let messages = send(&mut runtime, command);
    expect_error_code(&messages, "invalid_params");
}

#[test]
fn sync_placeholder_matches_bpm_without_claiming_phase_alignment() {
    let mut runtime = new_runtime();
    let (mut session, _) = hello(&mut runtime, 1);
    load_ready(&mut runtime, &mut session, "A", "t-a");

    let command = session.command(
        "deck.load",
        json!({
            "deck": "B",
            "track": {
                "trackId": "t-b",
                "path": "/fixtures/b.wav",
                "durationMs": TRACK_DURATION_MS,
                "bpm": 62.0
            }
        }),
    );
    send(&mut runtime, command);
    let advance = session.command("sim.advanceTime", json!({ "ms": 150 }));
    send(&mut runtime, advance);

    let command = session.command(
        "deck.sync.set",
        json!({ "deck": "B", "enabled": true, "leader": "A" }),
    );
    let messages = send(&mut runtime, command);
    let data = &expect_result(&messages)["data"];
    assert_eq!(data["rate"], 2.0);
    // 位相合わせは未実装であることをプロトコル上も明示する。
    assert_eq!(data["phaseAligned"], false);
}

// ---------------------------------------------------------------- 失効 ID

#[test]
fn stale_session_id_is_rejected() {
    let mut runtime = new_runtime();
    let (mut session, _) = hello(&mut runtime, 1);
    let mut command = session.command("state.snapshot", json!({}));
    command["sessionId"] = json!("eng-test-s99");
    let messages = send(&mut runtime, command);
    expect_error_code(&messages, "session_mismatch");
}

#[test]
fn mismatched_engine_id_is_rejected() {
    let mut runtime = new_runtime();
    let (mut session, _) = hello(&mut runtime, 1);
    let mut command = session.command("state.snapshot", json!({}));
    command["engineId"] = json!("eng-somebody-else");
    let messages = send(&mut runtime, command);
    expect_error_code(&messages, "engine_mismatch");
}

#[test]
fn non_increasing_command_id_is_rejected() {
    let mut runtime = new_runtime();
    let (mut session, _) = hello(&mut runtime, 1);
    let command = session.command("state.snapshot", json!({}));
    send(&mut runtime, command.clone());
    // 同じ id をそのまま再送する。
    let messages = send(&mut runtime, command);
    expect_error_code(&messages, "stale_command_id");
}

#[test]
fn rehello_invalidates_previous_session_but_preserves_playback_state() {
    let mut runtime = new_runtime();
    let (mut session, _) = hello(&mut runtime, 1);
    load_ready(&mut runtime, &mut session, "A", "t-1");
    let command = session.command("deck.play", json!({ "deck": "A" }));
    send(&mut runtime, command);
    let advance = session.command("sim.advanceTime", json!({ "ms": 2000 }));
    send(&mut runtime, advance);
    let old_session_id = session.session_id.clone();

    // Webview の再読み込み相当。コマンド ID 空間もリセットされる。
    let (mut fresh, messages) = hello(&mut runtime, 1);
    assert_ne!(fresh.session_id, old_session_id);
    let invalidated =
        find_event(&messages, "session.invalidated").expect("session.invalidated が来ること");
    assert_eq!(invalidated["data"]["sessionId"], old_session_id);

    // 再生は継続しており、スナップショットで復元できる。
    let command = fresh.command("state.snapshot", json!({}));
    let messages = send(&mut runtime, command);
    let snapshot = &expect_result(&messages)["data"];
    assert_eq!(snapshot["decks"]["A"]["status"], "playing");
    assert!(snapshot["decks"]["A"]["positionMs"].as_f64().unwrap() >= 2000.0);

    // 古いセッション ID の命令は誤適用されない。
    let stale = json!({
        "protocol": 1,
        "id": 500,
        "sessionId": old_session_id,
        "engineId": fresh.engine_id,
        "op": "deck.pause",
        "params": { "deck": "A" },
    });
    let messages = send(&mut runtime, stale);
    expect_error_code(&messages, "session_mismatch");
}

// ---------------------------------------------------------------- 異常入力

#[test]
fn malformed_json_returns_structured_error_without_crashing() {
    let mut runtime = new_runtime();
    let messages = runtime.handle_line("{ this is not json");
    let value = serde_json::to_value(&messages[0]).unwrap();
    assert_eq!(value["kind"], "error");
    assert_eq!(value["error"]["code"], "malformed_message");

    // 続けて正常なコマンドを処理できる。
    let (_session, messages) = hello(&mut runtime, 1);
    assert_eq!(messages[0]["kind"], "hello");
}

#[test]
fn blank_lines_are_ignored() {
    let mut runtime = new_runtime();
    assert!(runtime.handle_line("   ").is_empty());
    assert!(runtime.handle_line("").is_empty());
}

#[test]
fn missing_required_field_is_reported_with_command_id() {
    let mut runtime = new_runtime();
    // op が無い（id は拾えるので相関できる）。
    let messages = send(&mut runtime, json!({ "protocol": 1, "id": 7 }));
    let error = expect_error_code(&messages, "malformed_message");
    assert_eq!(error["id"], 7);
}

#[test]
fn unknown_protocol_version_is_rejected() {
    let mut runtime = new_runtime();
    let messages = send(
        &mut runtime,
        json!({ "protocol": 99, "id": 1, "op": "session.hello", "params": {} }),
    );
    let error = expect_error_code(&messages, "protocol_version_unsupported");
    assert_eq!(error["error"]["details"]["max"], 1);
}

#[test]
fn unknown_op_is_distinguished_from_unsupported_op() {
    let mut runtime = new_runtime();
    let (mut session, _) = hello(&mut runtime, 1);

    let command = session.command("deck.scratch.nudge", json!({ "deck": "A" }));
    let messages = send(&mut runtime, command);
    expect_error_code(&messages, "unknown_op");

    // 既知だがこのビルドでは提供しない操作。
    let mut wall_clock = Runtime::new(Engine::new(config(false)));
    let (mut wall_session, _) = hello(&mut wall_clock, 1);
    let command = wall_session.command("sim.advanceTime", json!({ "ms": 10 }));
    let messages = send(&mut wall_clock, command);
    expect_error_code(&messages, "unsupported_operation");
}

#[test]
fn unknown_deck_is_reported_as_deck_not_found() {
    let mut runtime = new_runtime();
    let (mut session, _) = hello(&mut runtime, 1);
    let command = session.command("deck.play", json!({ "deck": "C" }));
    let messages = send(&mut runtime, command);
    let error = expect_error_code(&messages, "deck_not_found");
    assert_eq!(error["error"]["details"]["known"], json!(["A", "B"]));
}

#[test]
fn out_of_range_and_wrongly_typed_params_are_rejected() {
    let mut runtime = new_runtime();
    let (mut session, _) = hello(&mut runtime, 1);
    load_ready(&mut runtime, &mut session, "A", "t-1");

    let cases: Vec<(&str, Value)> = vec![
        ("deck.seek", json!({ "deck": "A", "positionMs": -1 })),
        (
            "deck.seek",
            json!({ "deck": "A", "positionMs": TRACK_DURATION_MS + 1.0 }),
        ),
        ("deck.seek", json!({ "deck": "A", "positionMs": "start" })),
        ("deck.tempo.set", json!({ "deck": "A", "rate": 10.0 })),
        ("mixer.channel.gain", json!({ "deck": "A", "gain": 1.5 })),
        ("mixer.crossfader", json!({ "position": -2.0 })),
        (
            "mixer.channel.eq",
            json!({ "deck": "A", "band": "air", "gain": 1.0 }),
        ),
        (
            "deck.loop.set",
            json!({ "deck": "A", "startMs": 2000, "endMs": 1000 }),
        ),
    ];

    for (op, params) in cases {
        let command = session.command(op, params);
        let messages = send(&mut runtime, command);
        expect_error_code(&messages, "invalid_params");
    }
}

#[test]
fn audio_config_rejects_overlapping_master_and_pfl_channels() {
    let mut runtime = new_runtime();
    let (mut session, _) = hello(&mut runtime, 1);

    let command = session.command(
        "audio.config.set",
        json!({ "masterChannels": [0, 1], "pflChannels": [1, 2] }),
    );
    let messages = send(&mut runtime, command);
    expect_error_code(&messages, "invalid_params");

    let command = session.command(
        "audio.config.set",
        json!({ "deviceId": "sim:four-channel", "masterChannels": [0, 1], "pflChannels": [2, 3] }),
    );
    let messages = send(&mut runtime, command);
    let data = &expect_result(&messages)["data"];
    assert_eq!(data["pflChannels"], json!([2, 3]));
    // 実デバイスは開いていない。
    assert_eq!(data["applied"], false);
}

#[test]
fn meters_are_opt_in_and_labelled_simulated() {
    let mut runtime = new_runtime();
    let (mut session, _) = hello(&mut runtime, 1);
    load_ready(&mut runtime, &mut session, "A", "t-1");
    let command = session.command("deck.play", json!({ "deck": "A" }));
    send(&mut runtime, command);

    let advance = session.command("sim.advanceTime", json!({ "ms": 200 }));
    let messages = send(&mut runtime, advance);
    assert!(find_event(&messages, "meters").is_none(), "既定では無効");

    let command = session.command(
        "meters.subscribe",
        json!({ "enabled": true, "intervalMs": 100 }),
    );
    let messages = send(&mut runtime, command);
    assert_eq!(expect_result(&messages)["data"]["simulated"], true);

    let advance = session.command("sim.advanceTime", json!({ "ms": 200 }));
    let messages = send(&mut runtime, advance);
    let meters = find_event(&messages, "meters").expect("meters が来ること");
    assert_eq!(meters["data"]["simulated"], true);
}

#[test]
fn unknown_fields_are_ignored_for_forward_compatibility() {
    let mut runtime = new_runtime();
    let (mut session, _) = hello(&mut runtime, 1);
    let mut command = session.command("state.snapshot", json!({}));
    command["futureField"] = json!({ "added": "in v2" });
    let messages = send(&mut runtime, command);
    expect_result(&messages);
}

#[test]
fn wall_clock_tick_events_follow_the_command_reply() {
    let mut runtime = Runtime::new(Engine::new(config(false)));
    let (mut session, _) = hello(&mut runtime, 1);

    let load = session.command(
        "deck.load",
        json!({ "deck": "A", "track": fixture_track("ordering") }),
    );
    runtime.process(Some(0.0), &load.to_string());

    let play = session.command("deck.play", json!({ "deck": "A" }));
    let messages: Vec<Value> = runtime
        .process(Some(200.0), &play.to_string())
        .iter()
        .map(|message| serde_json::to_value(message).unwrap())
        .collect();

    assert_eq!(messages.first().unwrap()["kind"], "result");
    assert_eq!(messages.first().unwrap()["op"], "deck.play");
    assert!(find_event(&messages, "deck.loaded").is_some());
    let event_sequences: Vec<u64> = messages
        .iter()
        .filter(|message| message["kind"] == "event")
        .map(|message| message["seq"].as_u64().unwrap())
        .collect();
    assert!(event_sequences.windows(2).all(|pair| pair[0] < pair[1]));
}
