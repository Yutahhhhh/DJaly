//! プロセス境界の契約テスト。
//!
//! 実際に `dj-engine-sim` を子プロセスとして起動し、stdin/stdout の
//! NDJSON だけでやり取りする。Tauri スーパーバイザが将来 C++ ホストに
//! 対して行うのと同じ操作を、同じ経路で検証する。
//!
//! 決定論モードで起動し、コマンドの区切りには `engine.ping` を
//! フェンスとして使う。待ち時間に依存した判定はしない。

use std::io::{BufRead, BufReader, Write};
use std::process::{Child, ChildStdin, Command, Stdio};
use std::sync::mpsc::{self, Receiver, RecvTimeoutError};
use std::thread;
use std::time::{Duration, Instant};

use serde_json::{json, Value};

const TIMEOUT: Duration = Duration::from_secs(10);
const ENGINE_ID: &str = "eng-process-test";

struct Harness {
    child: Child,
    stdin: Option<ChildStdin>,
    receiver: Receiver<String>,
    next_id: u64,
    session_id: String,
}

impl Harness {
    fn start() -> Harness {
        let mut child = Command::new(env!("CARGO_BIN_EXE_dj-engine-sim"))
            .arg("--deterministic")
            .arg(format!("--engine-id={ENGINE_ID}"))
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::inherit())
            .spawn()
            .expect("シミュレータを起動できること");

        let stdin = child.stdin.take().expect("stdin を取得できること");
        let stdout = child.stdout.take().expect("stdout を取得できること");
        let (sender, receiver) = mpsc::channel();
        thread::spawn(move || {
            for line in BufReader::new(stdout).lines() {
                match line {
                    Ok(line) => {
                        if sender.send(line).is_err() {
                            break;
                        }
                    }
                    Err(_) => break,
                }
            }
        });

        Harness {
            child,
            stdin: Some(stdin),
            receiver,
            next_id: 0,
            session_id: String::new(),
        }
    }

    fn take_id(&mut self) -> u64 {
        self.next_id += 1;
        self.next_id
    }

    fn write_line(&mut self, line: &str) {
        let stdin = self.stdin.as_mut().expect("stdin が開いていること");
        stdin
            .write_all(line.as_bytes())
            .expect("stdin へ書き込めること");
        stdin.write_all(b"\n").expect("改行を書き込めること");
        stdin.flush().expect("flush できること");
    }

    fn read_line(&self) -> Value {
        match self.receiver.recv_timeout(TIMEOUT) {
            Ok(line) => serde_json::from_str(&line).unwrap_or_else(|error| {
                panic!("stdout が NDJSON ではありません: {error} / {line}")
            }),
            Err(RecvTimeoutError::Timeout) => panic!("{TIMEOUT:?} 以内に応答がありませんでした"),
            Err(RecvTimeoutError::Disconnected) => panic!("エンジンが stdout を閉じました"),
        }
    }

    /// ハンドシェイク。セッション ID を保持する。
    fn hello(&mut self) -> Value {
        let id = self.take_id();
        self.write_line(
            &json!({
                "protocol": 1,
                "kind": "command",
                "id": id,
                "op": "session.hello",
                "params": { "clientName": "process-test" },
            })
            .to_string(),
        );
        let greeting = self.read_line();
        assert_eq!(greeting["kind"], "hello", "得られた値: {greeting}");
        self.session_id = greeting["sessionId"]
            .as_str()
            .expect("sessionId があること")
            .to_string();
        greeting
    }

    /// コマンドを送り、`engine.ping` をフェンスにして、そのコマンドが
    /// 生んだメッセージだけを収集する。
    fn exchange(&mut self, op: &str, params: Value) -> Vec<Value> {
        let id = self.take_id();
        let session_id = self.session_id.clone();
        self.write_line(
            &json!({
                "protocol": 1,
                "kind": "command",
                "id": id,
                "sessionId": session_id,
                "engineId": ENGINE_ID,
                "op": op,
                "params": params,
            })
            .to_string(),
        );
        self.drain_to_fence()
    }

    /// 任意の生 JSON を送ってから収集する（異常系用）。
    fn exchange_raw(&mut self, line: &str) -> Vec<Value> {
        self.write_line(line);
        self.drain_to_fence()
    }

    fn drain_to_fence(&mut self) -> Vec<Value> {
        let fence_id = self.take_id();
        let session_id = self.session_id.clone();
        self.write_line(
            &json!({
                "protocol": 1,
                "kind": "command",
                "id": fence_id,
                "sessionId": session_id,
                "engineId": ENGINE_ID,
                "op": "engine.ping",
                "params": {},
            })
            .to_string(),
        );

        let mut collected = Vec::new();
        loop {
            let value = self.read_line();
            if value["kind"] == "result" && value["id"].as_u64() == Some(fence_id) {
                return collected;
            }
            collected.push(value);
        }
    }

    fn close_stdin(&mut self) {
        self.stdin.take();
    }
}

impl Drop for Harness {
    fn drop(&mut self) {
        self.stdin.take();
        let _ = self.child.kill();
        let _ = self.child.wait();
    }
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

fn fixture_track() -> Value {
    json!({
        "trackId": "fixture-1",
        "path": "/fixtures/does-not-need-to-exist.wav",
        "title": "Fixture Track",
        "durationMs": 180_000.0,
        "bpm": 128.0,
        "sampleRateHz": 44_100,
        "channels": 2
    })
}

#[test]
fn stdio_lifecycle_load_play_and_snapshot() {
    let mut harness = Harness::start();

    let greeting = harness.hello();
    assert_eq!(greeting["engineId"], ENGINE_ID);
    assert_eq!(greeting["engine"]["simulated"], true);
    assert_eq!(greeting["engine"]["deterministic"], true);

    // 非同期ロード: 受理応答が先、完了は時間を進めてから。
    let messages = harness.exchange(
        "deck.load",
        json!({ "deck": "A", "track": fixture_track() }),
    );
    let result = find(&messages, "result").expect("result が来ること");
    assert_eq!(result["data"]["accepted"], true);
    assert!(find_event(&messages, "deck.loaded").is_none());

    let messages = harness.exchange("sim.advanceTime", json!({ "ms": 200 }));
    let loaded = find_event(&messages, "deck.loaded").expect("deck.loaded が来ること");
    assert_eq!(loaded["data"]["track"]["trackId"], "fixture-1");

    harness.exchange("deck.play", json!({ "deck": "A" }));
    let messages = harness.exchange("sim.advanceTime", json!({ "ms": 4_000 }));
    let position = find_event(&messages, "deck.position").expect("deck.position が来ること");
    let position_ms = position["data"]["decks"]["A"]["positionMs"]
        .as_f64()
        .unwrap();
    assert!(
        (position_ms - 4_000.0).abs() < 1e-6,
        "得られた値: {position_ms}"
    );

    // スナップショットで UI を復元できる。
    let messages = harness.exchange("state.snapshot", json!({}));
    let snapshot = find(&messages, "result").expect("result")["data"].clone();
    assert_eq!(snapshot["decks"]["A"]["status"], "playing");
    assert_eq!(snapshot["decks"]["B"]["status"], "empty");
    assert!(snapshot["rev"].as_u64().unwrap() > 0);
}

#[test]
fn stdio_rejects_stale_ids_and_malformed_lines() {
    let mut harness = Harness::start();
    harness.hello();

    // 壊れた行でプロセスは落ちない。
    let messages = harness.exchange_raw("{ not json at all");
    let error = find(&messages, "error").expect("error が来ること");
    assert_eq!(error["error"]["code"], "malformed_message");

    // 失効したセッション ID。
    let id = harness.take_id();
    let line = json!({
        "protocol": 1,
        "id": id,
        "sessionId": "eng-process-test-s99",
        "engineId": ENGINE_ID,
        "op": "state.snapshot",
        "params": {},
    })
    .to_string();
    let messages = harness.exchange_raw(&line);
    let error = find(&messages, "error").expect("error が来ること");
    assert_eq!(error["error"]["code"], "session_mismatch");

    // 別エンジンインスタンス宛の命令。
    let id = harness.take_id();
    let session_id = harness.session_id.clone();
    let line = json!({
        "protocol": 1,
        "id": id,
        "sessionId": session_id,
        "engineId": "eng-someone-else",
        "op": "state.snapshot",
        "params": {},
    })
    .to_string();
    let messages = harness.exchange_raw(&line);
    let error = find(&messages, "error").expect("error が来ること");
    assert_eq!(error["error"]["code"], "engine_mismatch");

    // 一連の異常のあとも正常動作を継続する。
    let messages = harness.exchange("state.snapshot", json!({}));
    assert!(find(&messages, "result").is_some());
}

#[test]
fn closing_stdin_terminates_the_engine_process() {
    let mut harness = Harness::start();
    harness.hello();
    harness.close_stdin();

    let deadline = Instant::now() + TIMEOUT;
    loop {
        match harness.child.try_wait().expect("try_wait が成功すること") {
            Some(status) => {
                assert!(status.success(), "正常終了すること: {status:?}");
                return;
            }
            None => {
                if Instant::now() > deadline {
                    panic!("stdin を閉じてもエンジンが終了しませんでした");
                }
                thread::sleep(Duration::from_millis(20));
            }
        }
    }
}

#[test]
fn wall_clock_tick_and_command_events_are_published_in_sequence_order() {
    let mut child = Command::new(env!("CARGO_BIN_EXE_dj-engine-sim"))
        .arg(format!("--engine-id={ENGINE_ID}"))
        .arg("--tick-ms=1")
        .arg("--load-latency-ms=0")
        .arg("--position-interval-ms=1")
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::null())
        .spawn()
        .expect("シミュレータを起動できること");

    let mut stdin = child.stdin.take().unwrap();
    let stdout = child.stdout.take().unwrap();
    writeln!(
        stdin,
        "{}",
        json!({ "protocol": 1, "id": 1, "op": "session.hello", "params": {} })
    )
    .unwrap();
    stdin.flush().unwrap();

    let mut reader = BufReader::new(stdout);
    let mut hello_line = String::new();
    reader.read_line(&mut hello_line).unwrap();
    let hello: Value = serde_json::from_str(&hello_line).unwrap();
    let session_id = hello["sessionId"].as_str().unwrap();

    for (id, op, params) in [
        (
            2,
            "deck.load",
            json!({ "deck": "A", "track": fixture_track() }),
        ),
        (3, "deck.play", json!({ "deck": "A" })),
    ] {
        writeln!(
            stdin,
            "{}",
            json!({
                "protocol": 1, "id": id, "sessionId": session_id,
                "engineId": ENGINE_ID, "op": op, "params": params
            })
        )
        .unwrap();
    }
    for id in 4..104 {
        writeln!(
            stdin,
            "{}",
            json!({
                "protocol": 1, "id": id, "sessionId": session_id,
                "engineId": ENGINE_ID, "op": "mixer.crossfader",
                "params": { "position": ((id % 20) as f64 / 10.0) - 1.0 }
            })
        )
        .unwrap();
    }
    stdin.flush().unwrap();
    thread::sleep(Duration::from_millis(50));
    drop(stdin);

    let mut lines = Vec::new();
    for line in reader.lines() {
        lines.push(serde_json::from_str::<Value>(&line.unwrap()).unwrap());
    }
    let status = child.wait().unwrap();
    assert!(status.success());

    let sequences: Vec<u64> = lines
        .iter()
        .filter(|message| message["kind"] == "event")
        .map(|message| message["seq"].as_u64().unwrap())
        .collect();
    assert!(sequences.len() > 20, "十分な並行eventが発生すること");
    assert!(
        sequences.windows(2).all(|pair| pair[0] < pair[1]),
        "event seqがwire上で逆転しています: {sequences:?}"
    );
}
