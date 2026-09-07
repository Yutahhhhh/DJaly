//! DJaly ネイティブエンジンのワイヤプロトコル定義。
//!
//! 1行1 JSON オブジェクト（NDJSON, UTF-8, `\n` 終端）で、
//! クライアント（Tauri スーパーバイザ）→エンジンが [`Command`]、
//! エンジン→クライアントが [`Outgoing`]。
//!
//! この型定義はトランスポート非依存であり、将来 Mixxx 由来の C++ ホストに
//! 置き換わっても JSON スキーマは同一である必要がある。

use serde::de::DeserializeOwned;
use serde::{Deserialize, Serialize};
use serde_json::{Map, Value};

/// 現在のプロトコルバージョン。互換性を壊す変更でのみ上げる。
pub const PROTOCOL_VERSION: u32 = 1;
/// 受理できる最小バージョン。
pub const PROTOCOL_MIN_VERSION: u32 = 1;

/// 論理デッキ識別子。Phase 0 は 2 デッキのみ。
///
/// 音声チャンネル番号とは別概念であり、混同しない。
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Hash, Serialize, Deserialize)]
pub enum DeckId {
    #[serde(rename = "A")]
    A,
    #[serde(rename = "B")]
    B,
}

impl DeckId {
    pub const ALL: [DeckId; 2] = [DeckId::A, DeckId::B];

    pub fn as_str(self) -> &'static str {
        match self {
            DeckId::A => "A",
            DeckId::B => "B",
        }
    }

    /// 文字列からデッキを解決する。未知の値は `None`（呼び出し側が
    /// `deck_not_found` を返す）。
    pub fn parse(raw: &str) -> Option<DeckId> {
        match raw {
            "A" | "a" => Some(DeckId::A),
            "B" | "b" => Some(DeckId::B),
            _ => None,
        }
    }
}

impl std::fmt::Display for DeckId {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(self.as_str())
    }
}

/// 操作名。文字列定数として公開し、Rust 以外の実装からも参照できるようにする。
pub mod op {
    pub const SESSION_HELLO: &str = "session.hello";
    pub const ENGINE_PING: &str = "engine.ping";
    pub const STATE_SNAPSHOT: &str = "state.snapshot";

    pub const DECK_LOAD: &str = "deck.load";
    pub const DECK_UNLOAD: &str = "deck.unload";
    pub const DECK_PLAY: &str = "deck.play";
    pub const DECK_PAUSE: &str = "deck.pause";
    pub const DECK_SEEK: &str = "deck.seek";
    pub const DECK_TEMPO_SET: &str = "deck.tempo.set";
    pub const DECK_KEYLOCK_SET: &str = "deck.keylock.set";
    pub const DECK_SYNC_SET: &str = "deck.sync.set";
    pub const DECK_HOTCUE_SET: &str = "deck.hotcue.set";
    pub const DECK_HOTCUE_JUMP: &str = "deck.hotcue.jump";
    pub const DECK_HOTCUE_CLEAR: &str = "deck.hotcue.clear";
    pub const DECK_LOOP_SET: &str = "deck.loop.set";
    pub const DECK_LOOP_ENABLE: &str = "deck.loop.enable";

    pub const MIXER_CHANNEL_GAIN: &str = "mixer.channel.gain";
    pub const MIXER_CHANNEL_EQ: &str = "mixer.channel.eq";
    pub const MIXER_CHANNEL_PFL: &str = "mixer.channel.pfl";
    pub const MIXER_CROSSFADER: &str = "mixer.crossfader";
    pub const MIXER_MASTER_GAIN: &str = "mixer.master.gain";

    pub const AUDIO_DEVICES_LIST: &str = "audio.devices.list";
    pub const AUDIO_CONFIG_GET: &str = "audio.config.get";
    pub const AUDIO_CONFIG_SET: &str = "audio.config.set";

    pub const METERS_SUBSCRIBE: &str = "meters.subscribe";

    /// シミュレータ専用。決定論モードで時間を進める。実ホストには存在しない。
    pub const SIM_ADVANCE_TIME: &str = "sim.advanceTime";
}

/// イベント名。
pub mod event {
    pub const DECK_STATE: &str = "deck.state";
    pub const DECK_POSITION: &str = "deck.position";
    pub const DECK_LOADED: &str = "deck.loaded";
    pub const DECK_LOAD_FAILED: &str = "deck.load.failed";
    pub const MIXER_STATE: &str = "mixer.state";
    pub const AUDIO_CONFIG: &str = "audio.config";
    pub const METERS: &str = "meters";
    pub const SESSION_INVALIDATED: &str = "session.invalidated";
}

/// 構造化エラーコード。未対応操作と不正入力を区別できるようにする。
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ErrorCode {
    /// 行が JSON として解釈できない、または必須フィールドが欠けている。
    MalformedMessage,
    /// `protocol` がこのエンジンの受理範囲外。
    ProtocolVersionUnsupported,
    /// `op` が未知。
    UnknownOp,
    /// `op` は既知だがこのビルドでは実装されていない。
    UnsupportedOperation,
    /// パラメータの型・範囲・単位が不正。
    InvalidParams,
    /// `session.hello` 前に他の操作が来た。
    SessionRequired,
    /// `sessionId` が現行セッションと一致しない（再読み込み前の古い命令）。
    SessionMismatch,
    /// `engineId` が現行エンジンインスタンスと一致しない。
    EngineMismatch,
    /// `id` が単調増加していない（再送・巻き戻し）。
    StaleCommandId,
    /// 指定デッキが存在しない。
    DeckNotFound,
    /// デッキに曲がロードされていない。
    NoTrackLoaded,
    /// ロード中で操作を受け付けられない。
    TrackNotReady,
    /// エンジン内部の想定外エラー。
    Internal,
}

impl ErrorCode {
    /// 同じ命令をそのまま再送して回復しうるか。
    pub fn retryable(self) -> bool {
        matches!(self, ErrorCode::TrackNotReady | ErrorCode::Internal)
    }
}

/// エラー本体。
#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct ProtocolError {
    pub code: ErrorCode,
    pub message: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub details: Option<Value>,
    pub retryable: bool,
}

impl ProtocolError {
    pub fn new(code: ErrorCode, message: impl Into<String>) -> Self {
        ProtocolError {
            code,
            message: message.into(),
            details: None,
            retryable: code.retryable(),
        }
    }

    pub fn with_details(mut self, details: Value) -> Self {
        self.details = Some(details);
        self
    }

    pub fn invalid_params(message: impl Into<String>) -> Self {
        ProtocolError::new(ErrorCode::InvalidParams, message)
    }

    pub fn deck_not_found(raw: &str) -> Self {
        ProtocolError::new(
            ErrorCode::DeckNotFound,
            format!("未知のデッキ識別子: {raw}"),
        )
        .with_details(serde_json::json!({ "known": ["A", "B"] }))
    }
}

/// クライアント→エンジンのコマンド。
///
/// 未知フィールドは前方互換のため無視する（`deny_unknown_fields` は付けない）。
#[derive(Debug, Clone, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct Command {
    /// 送信側が想定するプロトコルバージョン。省略時は現行とみなす。
    #[serde(default)]
    pub protocol: Option<u32>,
    /// 常に `"command"`。将来の多重化用。
    #[serde(default)]
    pub kind: Option<String>,
    /// セッション内で厳密に単調増加するコマンド ID。
    pub id: u64,
    /// `session.hello` 以外では必須。
    #[serde(default)]
    pub session_id: Option<String>,
    /// `session.hello` 以外では必須。
    #[serde(default)]
    pub engine_id: Option<String>,
    pub op: String,
    #[serde(default)]
    pub params: Value,
}

/// エンジンの自己申告情報。
#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct EngineInfo {
    pub name: String,
    pub version: String,
    /// `"simulator"` または将来の `"mixxx"`。
    pub implementation: String,
    /// 音を出していないことを明示するフラグ。UI はこれを隠さず表示する。
    pub simulated: bool,
    /// 壁時計を使わない決定論モードか。
    pub deterministic: bool,
    pub decks: Vec<DeckId>,
    pub capabilities: Vec<String>,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct ProtocolRange {
    pub min: u32,
    pub max: u32,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct HelloMessage {
    pub protocol: u32,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub id: Option<u64>,
    pub engine_id: String,
    pub session_id: String,
    pub rev: u64,
    pub engine: EngineInfo,
    pub protocol_versions: ProtocolRange,
    pub engine_time_ms: f64,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct ResultMessage {
    pub protocol: u32,
    pub id: u64,
    pub engine_id: String,
    pub session_id: String,
    pub op: String,
    pub rev: u64,
    pub data: Value,
    pub engine_time_ms: f64,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct ErrorMessage {
    pub protocol: u32,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub id: Option<u64>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub engine_id: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub op: Option<String>,
    pub rev: u64,
    pub error: ProtocolError,
    pub engine_time_ms: f64,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct EventMessage {
    pub protocol: u32,
    pub engine_id: String,
    pub event: String,
    /// イベント通し番号。欠落検出用。
    pub seq: u64,
    /// このイベント時点の状態リビジョン。
    pub rev: u64,
    pub data: Value,
    pub engine_time_ms: f64,
}

/// エンジン→クライアントの全メッセージ。`kind` で判別する。
#[derive(Debug, Clone, Serialize)]
#[serde(tag = "kind", rename_all = "camelCase")]
pub enum Outgoing {
    Hello(HelloMessage),
    Result(ResultMessage),
    Error(ErrorMessage),
    Event(EventMessage),
}

impl Outgoing {
    /// NDJSON の 1 行に直列化する。改行は含まない。
    pub fn to_line(&self) -> Result<String, serde_json::Error> {
        serde_json::to_string(self)
    }
}

/// `params` を型付き構造体に変換する。`null` は空オブジェクトとして扱う。
pub fn parse_params<T: DeserializeOwned>(params: &Value) -> Result<T, ProtocolError> {
    let value = if params.is_null() {
        Value::Object(Map::new())
    } else {
        params.clone()
    };
    serde_json::from_value(value)
        .map_err(|e| ProtocolError::invalid_params(format!("params が不正です: {e}")))
}

/// 有限な f64 のみ通す。NaN / Inf は serde_json が直列化できず、
/// 音声処理でも即座に破綻するため境界で弾く。
pub fn finite(value: f64, field: &str) -> Result<f64, ProtocolError> {
    if value.is_finite() {
        Ok(value)
    } else {
        Err(ProtocolError::invalid_params(format!(
            "{field} は有限の数値である必要があります"
        )))
    }
}

/// 閉区間 `[min, max]` に収まっているか検査する（クランプはしない）。
pub fn in_range(value: f64, min: f64, max: f64, field: &str) -> Result<f64, ProtocolError> {
    let value = finite(value, field)?;
    if value < min || value > max {
        return Err(ProtocolError::invalid_params(format!(
            "{field} は {min} 以上 {max} 以下である必要があります（受信値: {value}）"
        )));
    }
    Ok(value)
}
