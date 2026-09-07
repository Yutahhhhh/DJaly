//! NDJSON ディスパッチ層。
//!
//! 1 行 = 1 コマンド。応答は「返信（result / error / hello）が先、
//! そのコマンドが生んだイベントが後」の順で書き出す。
//! ログは stderr のみに出す。stdout はプロトコル専用。

use std::io::{self, Write};

use serde_json::{json, Value};

use crate::engine::Engine;
use crate::protocol::{
    op, Command, ErrorCode, ErrorMessage, Outgoing, ProtocolError, ResultMessage,
    PROTOCOL_MIN_VERSION, PROTOCOL_VERSION,
};

pub struct Runtime {
    engine: Engine,
}

impl Runtime {
    pub fn new(engine: Engine) -> Self {
        Runtime { engine }
    }

    pub fn engine(&self) -> &Engine {
        &self.engine
    }

    pub fn engine_mut(&mut self) -> &mut Engine {
        &mut self.engine
    }

    /// 壁時計モードで使う。時刻を進めた結果のイベントだけを返す。
    pub fn tick(&mut self, now_ms: f64) -> Vec<Outgoing> {
        self.engine
            .tick(now_ms)
            .into_iter()
            .map(Outgoing::Event)
            .collect()
    }

    /// 時刻を進めてから 1 行処理する。`now_ms` が `None` なら時刻は進めない
    /// （決定論モード。時間は `sim.advanceTime` でのみ進む）。
    pub fn process(&mut self, now_ms: Option<f64>, line: &str) -> Vec<Outgoing> {
        let tick_messages = match now_ms {
            Some(now) => self.tick(now),
            None => Vec::new(),
        };
        // tick() updates authoritative state before command handling, but its
        // notifications are emitted after the command reply as protocol v1 promises.
        let command_messages = self.handle_line(line);
        let mut replies = Vec::new();
        let mut command_events = Vec::new();
        for message in command_messages {
            match message {
                Outgoing::Event(_) => command_events.push(message),
                _ => replies.push(message),
            }
        }
        // tick events were assigned lower sequence numbers, so they must precede
        // command events even though the correlated reply remains first.
        replies.extend(tick_messages);
        replies.extend(command_events);
        replies
    }

    /// 1 行を処理する。空行は無視する。
    pub fn handle_line(&mut self, line: &str) -> Vec<Outgoing> {
        let trimmed = line.trim();
        if trimmed.is_empty() {
            return Vec::new();
        }

        let raw: Value = match serde_json::from_str(trimmed) {
            Ok(value) => value,
            Err(error) => {
                return vec![self.error(
                    None,
                    None,
                    ProtocolError::new(
                        ErrorCode::MalformedMessage,
                        format!("JSON として解釈できません: {error}"),
                    ),
                )]
            }
        };

        // 壊れたコマンドでも可能な限り id を拾って相関できるようにする。
        let fallback_id = raw.get("id").and_then(Value::as_u64);
        let fallback_op = raw.get("op").and_then(Value::as_str).map(str::to_string);

        let command: Command = match serde_json::from_value(raw) {
            Ok(command) => command,
            Err(error) => {
                return vec![self.error(
                    fallback_id,
                    fallback_op,
                    ProtocolError::new(
                        ErrorCode::MalformedMessage,
                        format!("コマンドの形式が不正です: {error}"),
                    ),
                )]
            }
        };

        if let Some(kind) = command.kind.as_deref() {
            if kind != "command" {
                return vec![self.error(
                    Some(command.id),
                    Some(command.op.clone()),
                    ProtocolError::new(
                        ErrorCode::MalformedMessage,
                        format!("kind は \"command\" である必要があります（受信値: {kind}）"),
                    ),
                )];
            }
        }

        if let Some(version) = command.protocol {
            if !(PROTOCOL_MIN_VERSION..=PROTOCOL_VERSION).contains(&version) {
                return vec![self.error(
                    Some(command.id),
                    Some(command.op.clone()),
                    ProtocolError::new(
                        ErrorCode::ProtocolVersionUnsupported,
                        "このエンジンが受理できないプロトコルバージョンです",
                    )
                    .with_details(json!({
                        "min": PROTOCOL_MIN_VERSION,
                        "max": PROTOCOL_VERSION,
                        "received": version,
                    })),
                )];
            }
        }

        if command.op == op::SESSION_HELLO {
            let (hello, events) = self.engine.begin_session(command.id);
            let mut messages = vec![Outgoing::Hello(hello)];
            messages.extend(events.into_iter().map(Outgoing::Event));
            return messages;
        }

        if let Err(error) = self.engine.authorize(
            command.id,
            command.session_id.as_deref(),
            command.engine_id.as_deref(),
        ) {
            return vec![self.error(Some(command.id), Some(command.op.clone()), error)];
        }

        let handled = self.engine.handle(&command.op, &command.params);
        let mut messages = Vec::new();
        match handled.outcome {
            Ok(data) => {
                let session_id = self.engine.session_id().unwrap_or_default().to_string();
                messages.push(Outgoing::Result(ResultMessage {
                    protocol: PROTOCOL_VERSION,
                    id: command.id,
                    engine_id: self.engine.engine_id().to_string(),
                    session_id,
                    op: command.op.clone(),
                    rev: self.engine.rev(),
                    data,
                    engine_time_ms: self.engine.now_ms(),
                }));
            }
            Err(error) => {
                messages.push(self.error(Some(command.id), Some(command.op.clone()), error));
            }
        }
        messages.extend(handled.events.into_iter().map(Outgoing::Event));
        messages
    }

    fn error(&self, id: Option<u64>, op_name: Option<String>, error: ProtocolError) -> Outgoing {
        Outgoing::Error(ErrorMessage {
            protocol: PROTOCOL_VERSION,
            id,
            engine_id: Some(self.engine.engine_id().to_string()),
            op: op_name,
            rev: self.engine.rev(),
            error,
            engine_time_ms: self.engine.now_ms(),
        })
    }
}

/// NDJSON として書き出す。1 メッセージ 1 行、書き終わりに flush する。
pub fn write_messages<W: Write>(writer: &mut W, messages: &[Outgoing]) -> io::Result<()> {
    for message in messages {
        match message.to_line() {
            Ok(line) => {
                writer.write_all(line.as_bytes())?;
                writer.write_all(b"\n")?;
            }
            Err(error) => {
                // 直列化不能なメッセージで接続全体を落とさない。
                eprintln!("[dj-engine-sim] メッセージの直列化に失敗しました: {error}");
            }
        }
    }
    writer.flush()
}
