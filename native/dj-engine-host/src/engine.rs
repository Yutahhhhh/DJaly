//! エンジンの権威状態機械。
//!
//! ここには I/O を持ち込まない。時刻は呼び出し側から与えられ、
//! 決定論モードではテストが `sim.advanceTime` で明示的に進める。
//! 設計書の「再生位置の正本は音声エンジン」に対応するのがこのモジュール。
//!
//! **音は出ない。** 位置の前進もメーター値もシミュレートされた値であり、
//! `EngineInfo::simulated` で常に自己申告する。

use serde::{Deserialize, Serialize};
use serde_json::{json, Value};

use crate::protocol::{
    event, finite, in_range, op, parse_params, DeckId, EngineInfo, ErrorCode, EventMessage,
    HelloMessage, ProtocolError, ProtocolRange, PROTOCOL_MIN_VERSION, PROTOCOL_VERSION,
};

/// 再生レートの受理範囲（倍率）。1.0 が原速。
pub const RATE_MIN: f64 = 0.25;
pub const RATE_MAX: f64 = 4.0;
/// EQ ゲインの受理範囲（線形倍率）。1.0 がユニティ（0 dB）。
pub const EQ_GAIN_MIN: f64 = 0.0;
pub const EQ_GAIN_MAX: f64 = 4.0;
/// ホットキュー本数。
pub const HOT_CUE_SLOTS: usize = 8;

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "camelCase")]
pub enum DeckStatus {
    Empty,
    Loading,
    Ready,
    Playing,
    Paused,
    Error,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct LoadedTrack {
    /// DJaly 側の正本 ID。エンジンは解釈せず保持するだけ。
    pub track_id: String,
    pub path: String,
    pub title: Option<String>,
    pub artist: Option<String>,
    pub duration_ms: f64,
    pub bpm: Option<f64>,
    pub sample_rate_hz: u32,
    pub channels: u16,
    pub beatgrid_offset_ms: f64,
}

#[derive(Debug, Clone, Copy, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct LoopRegion {
    pub start_ms: f64,
    pub end_ms: f64,
    pub enabled: bool,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct DeckState {
    pub deck: DeckId,
    pub status: DeckStatus,
    pub track: Option<LoadedTrack>,
    /// 再生位置（ミリ秒）。境界での正本単位はミリ秒。
    pub position_ms: f64,
    /// 同じ位置をフレーム（サンプル）で表したもの。単位変換を境界で明示する。
    pub position_frames: u64,
    /// 再生レート倍率。
    pub rate: f64,
    pub keylock: bool,
    pub sync_enabled: bool,
    pub sync_leader: Option<DeckId>,
    /// レート適用後の実効 BPM。ビートグリッド未知なら null。
    pub effective_bpm: Option<f64>,
    pub hot_cues: [Option<f64>; HOT_CUE_SLOTS],
    pub loop_region: Option<LoopRegion>,
    pub last_error: Option<String>,
    /// 進行中のロードを識別する。完了イベントの取り違えを防ぐ。
    pub load_id: Option<u64>,
}

impl DeckState {
    fn new(deck: DeckId) -> Self {
        DeckState {
            deck,
            status: DeckStatus::Empty,
            track: None,
            position_ms: 0.0,
            position_frames: 0,
            rate: 1.0,
            keylock: false,
            sync_enabled: false,
            sync_leader: None,
            effective_bpm: None,
            hot_cues: [None; HOT_CUE_SLOTS],
            loop_region: None,
            last_error: None,
            load_id: None,
        }
    }

    fn duration_ms(&self) -> f64 {
        self.track.as_ref().map(|t| t.duration_ms).unwrap_or(0.0)
    }

    fn sample_rate(&self) -> u32 {
        self.track
            .as_ref()
            .map(|t| t.sample_rate_hz)
            .unwrap_or(44_100)
    }

    fn refresh_derived(&mut self) {
        let sr = self.sample_rate() as f64;
        let frames = (self.position_ms / 1000.0) * sr;
        self.position_frames = if frames.is_finite() && frames > 0.0 {
            frames as u64
        } else {
            0
        };
        self.effective_bpm = self
            .track
            .as_ref()
            .and_then(|t| t.bpm)
            .map(|bpm| bpm * self.rate);
    }
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct ChannelState {
    pub deck: DeckId,
    /// チャンネルフェーダー。線形 0.0〜1.0。
    pub gain: f64,
    pub eq_low: f64,
    pub eq_mid: f64,
    pub eq_high: f64,
    pub pfl: bool,
}

impl ChannelState {
    fn new(deck: DeckId) -> Self {
        ChannelState {
            deck,
            gain: 1.0,
            eq_low: 1.0,
            eq_mid: 1.0,
            eq_high: 1.0,
            pfl: false,
        }
    }
}

#[derive(Debug, Clone)]
pub struct MixerState {
    /// -1.0 が A 全開、+1.0 が B 全開、0.0 がセンター。
    pub crossfader: f64,
    pub master_gain: f64,
    pub headphone_gain: f64,
    /// 0.0 = PFL のみ、1.0 = マスターのみ。
    pub headphone_mix: f64,
    pub channels: [ChannelState; 2],
}

/// 音声デバイス設定。シミュレータは実デバイスを一切開かない。
#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct AudioConfig {
    pub device_id: Option<String>,
    pub sample_rate_hz: u32,
    pub buffer_frames: u32,
    /// マスター出力に割り当てたチャンネル番号（0 始まり）。
    pub master_channels: [u16; 2],
    /// PFL（ヘッドホン）出力に割り当てたチャンネル番号。
    pub pfl_channels: [u16; 2],
    /// 実デバイスに適用されたか。シミュレータでは常に false。
    pub applied: bool,
}

#[derive(Debug, Clone)]
struct PendingLoad {
    deck: DeckId,
    load_id: u64,
    ready_at_ms: f64,
    fail: bool,
    track: LoadedTrack,
}

#[derive(Debug, Clone)]
pub struct EngineConfig {
    pub engine_id: String,
    pub version: String,
    pub implementation: String,
    pub deterministic: bool,
    /// 非同期ロードの模擬所要時間（ミリ秒）。
    pub load_latency_ms: f64,
    pub position_interval_ms: f64,
    pub meters_interval_ms: f64,
}

impl Default for EngineConfig {
    fn default() -> Self {
        EngineConfig {
            engine_id: "eng-default".to_string(),
            version: env!("CARGO_PKG_VERSION").to_string(),
            implementation: "simulator".to_string(),
            deterministic: false,
            load_latency_ms: 120.0,
            position_interval_ms: 50.0,
            meters_interval_ms: 100.0,
        }
    }
}

/// コマンド 1 件の処理結果。
pub struct Handled {
    pub outcome: Result<Value, ProtocolError>,
    pub events: Vec<EventMessage>,
}

pub struct Engine {
    config: EngineConfig,
    session_id: Option<String>,
    session_counter: u64,
    last_command_id: u64,
    rev: u64,
    seq: u64,
    now_ms: f64,
    decks: [DeckState; 2],
    mixer: MixerState,
    audio: AudioConfig,
    meters_enabled: bool,
    meters_interval_ms: f64,
    next_meters_ms: f64,
    next_position_ms: f64,
    pending_loads: Vec<PendingLoad>,
    next_load_id: u64,
}

impl Engine {
    pub fn new(config: EngineConfig) -> Self {
        let meters_interval_ms = config.meters_interval_ms;
        Engine {
            config,
            session_id: None,
            session_counter: 0,
            last_command_id: 0,
            rev: 0,
            seq: 0,
            now_ms: 0.0,
            decks: [DeckState::new(DeckId::A), DeckState::new(DeckId::B)],
            mixer: MixerState {
                crossfader: 0.0,
                master_gain: 1.0,
                headphone_gain: 0.5,
                headphone_mix: 0.0,
                channels: [ChannelState::new(DeckId::A), ChannelState::new(DeckId::B)],
            },
            audio: AudioConfig {
                device_id: None,
                sample_rate_hz: 44_100,
                buffer_frames: 512,
                master_channels: [0, 1],
                pfl_channels: [2, 3],
                applied: false,
            },
            meters_enabled: false,
            meters_interval_ms,
            next_meters_ms: 0.0,
            next_position_ms: 0.0,
            pending_loads: Vec::new(),
            next_load_id: 0,
        }
    }

    pub fn engine_id(&self) -> &str {
        &self.config.engine_id
    }

    pub fn session_id(&self) -> Option<&str> {
        self.session_id.as_deref()
    }

    pub fn rev(&self) -> u64 {
        self.rev
    }

    pub fn now_ms(&self) -> f64 {
        self.now_ms
    }

    pub fn deterministic(&self) -> bool {
        self.config.deterministic
    }

    pub fn info(&self) -> EngineInfo {
        EngineInfo {
            name: "dj-engine-sim".to_string(),
            version: self.config.version.clone(),
            implementation: self.config.implementation.clone(),
            simulated: true,
            deterministic: self.config.deterministic,
            decks: DeckId::ALL.to_vec(),
            capabilities: vec![
                "deck.load.async".to_string(),
                "deck.transport".to_string(),
                "deck.hotcue".to_string(),
                "deck.loop".to_string(),
                "deck.tempo".to_string(),
                "deck.keylock".to_string(),
                "deck.sync.placeholder".to_string(),
                "mixer.basic".to_string(),
                "audio.config.placeholder".to_string(),
                "meters.simulated".to_string(),
                "sim.time".to_string(),
            ],
        }
    }

    // ---------------------------------------------------------------- セッション

    /// 新しいクライアントセッションを開始する。
    ///
    /// 直前のセッションは無効化されるが、**デッキ状態は保持される**。
    /// これが「UI を再読み込みしても再生が継続する」ための前提になる。
    /// コマンド ID 空間はセッション境界でリセットされる。
    pub fn begin_session(&mut self, command_id: u64) -> (HelloMessage, Vec<EventMessage>) {
        let mut events = Vec::new();
        if let Some(previous) = self.session_id.take() {
            let data = json!({ "sessionId": previous, "reason": "superseded" });
            events.push(self.make_event(event::SESSION_INVALIDATED, data));
        }
        self.session_counter += 1;
        let session_id = format!("{}-s{}", self.config.engine_id, self.session_counter);
        self.session_id = Some(session_id.clone());
        self.last_command_id = command_id;

        let hello = HelloMessage {
            protocol: PROTOCOL_VERSION,
            id: Some(command_id),
            engine_id: self.config.engine_id.clone(),
            session_id,
            rev: self.rev,
            engine: self.info(),
            protocol_versions: ProtocolRange {
                min: PROTOCOL_MIN_VERSION,
                max: PROTOCOL_VERSION,
            },
            engine_time_ms: self.now_ms,
        };
        (hello, events)
    }

    /// セッション・エンジン ID とコマンド ID の単調性を検証する。
    pub fn authorize(
        &mut self,
        command_id: u64,
        session_id: Option<&str>,
        engine_id: Option<&str>,
    ) -> Result<(), ProtocolError> {
        let current = match self.session_id.as_deref() {
            Some(current) => current,
            None => {
                return Err(ProtocolError::new(
                    ErrorCode::SessionRequired,
                    "session.hello を先に実行してください",
                ))
            }
        };
        match engine_id {
            Some(value) if value == self.config.engine_id => {}
            Some(value) => {
                return Err(ProtocolError::new(
                    ErrorCode::EngineMismatch,
                    "engineId が現在のエンジンインスタンスと一致しません",
                )
                .with_details(json!({ "expected": self.config.engine_id, "received": value })))
            }
            None => {
                return Err(ProtocolError::new(
                    ErrorCode::EngineMismatch,
                    "engineId は必須です",
                ))
            }
        }
        match session_id {
            Some(value) if value == current => {}
            Some(value) => {
                return Err(ProtocolError::new(
                    ErrorCode::SessionMismatch,
                    "sessionId が失効しています。session.hello で再接続してください",
                )
                .with_details(json!({ "expected": current, "received": value })))
            }
            None => {
                return Err(ProtocolError::new(
                    ErrorCode::SessionRequired,
                    "sessionId は必須です",
                ))
            }
        }
        if command_id <= self.last_command_id {
            return Err(ProtocolError::new(
                ErrorCode::StaleCommandId,
                "コマンド ID はセッション内で厳密に単調増加する必要があります",
            )
            .with_details(
                json!({ "lastAccepted": self.last_command_id, "received": command_id }),
            ));
        }
        self.last_command_id = command_id;
        Ok(())
    }

    // ---------------------------------------------------------------- 時間

    /// 時刻を進め、その結果生じたイベントを返す。
    ///
    /// 時刻の巻き戻しは無視する（単調時計を前提とする）。
    pub fn tick(&mut self, now_ms: f64) -> Vec<EventMessage> {
        let mut events = Vec::new();
        if !now_ms.is_finite() || now_ms < self.now_ms {
            return events;
        }
        let dt = now_ms - self.now_ms;
        self.now_ms = now_ms;

        events.extend(self.resolve_pending_loads());
        events.extend(self.advance_playback(dt));
        events.extend(self.emit_periodic());
        events
    }

    fn resolve_pending_loads(&mut self) -> Vec<EventMessage> {
        let mut events = Vec::new();
        if self.pending_loads.is_empty() {
            return events;
        }
        let mut due = Vec::new();
        let mut keep = Vec::new();
        for pending in std::mem::take(&mut self.pending_loads) {
            if pending.ready_at_ms <= self.now_ms {
                due.push(pending);
            } else {
                keep.push(pending);
            }
        }
        self.pending_loads = keep;

        for pending in due {
            // 後続のロード / アンロードに追い越されていたら破棄する。
            if self.deck(pending.deck).load_id != Some(pending.load_id) {
                continue;
            }
            self.rev += 1;
            let deck_id = pending.deck;
            if pending.fail {
                {
                    let deck = self.deck_mut(deck_id);
                    deck.status = DeckStatus::Error;
                    deck.track = None;
                    deck.load_id = None;
                    deck.last_error = Some("シミュレートされたロード失敗".to_string());
                    deck.position_ms = 0.0;
                    deck.refresh_derived();
                }
                let data = json!({
                    "deck": deck_id,
                    "loadId": pending.load_id,
                    "trackId": pending.track.track_id,
                    "error": {
                        "code": "load_failed",
                        "message": "シミュレートされたロード失敗",
                    }
                });
                events.push(self.make_event(event::DECK_LOAD_FAILED, data));
            } else {
                {
                    let deck = self.deck_mut(deck_id);
                    deck.status = DeckStatus::Ready;
                    deck.track = Some(pending.track.clone());
                    deck.load_id = None;
                    deck.last_error = None;
                    deck.position_ms = 0.0;
                    deck.refresh_derived();
                }
                let data = json!({
                    "deck": deck_id,
                    "loadId": pending.load_id,
                    "track": pending.track,
                });
                events.push(self.make_event(event::DECK_LOADED, data));
            }
            let state_event = self.deck_state_event(deck_id);
            events.push(state_event);
        }
        events
    }

    fn advance_playback(&mut self, dt: f64) -> Vec<EventMessage> {
        let mut events = Vec::new();
        if dt <= 0.0 {
            return events;
        }
        for deck_id in DeckId::ALL {
            let mut reached_end = false;
            {
                let deck = self.deck_mut(deck_id);
                if deck.status != DeckStatus::Playing {
                    continue;
                }
                let duration = deck.duration_ms();
                let mut position = deck.position_ms + dt * deck.rate;

                if let Some(region) = deck.loop_region {
                    let length = region.end_ms - region.start_ms;
                    if region.enabled && length > 0.0 && position >= region.end_ms {
                        let overshoot = (position - region.start_ms) % length;
                        position = region.start_ms + overshoot;
                    }
                }
                if position >= duration {
                    position = duration;
                    deck.status = DeckStatus::Paused;
                    reached_end = true;
                }
                if position < 0.0 {
                    position = 0.0;
                }
                deck.position_ms = position;
                deck.refresh_derived();
            }
            if reached_end {
                self.rev += 1;
                let event = self.deck_state_event(deck_id);
                events.push(event);
            }
        }
        events
    }

    fn emit_periodic(&mut self) -> Vec<EventMessage> {
        let mut events = Vec::new();
        let any_playing = DeckId::ALL
            .iter()
            .any(|id| self.deck(*id).status == DeckStatus::Playing);

        if any_playing && self.now_ms >= self.next_position_ms {
            self.next_position_ms = self.now_ms + self.config.position_interval_ms;
            let data = json!({
                "decks": {
                    "A": self.position_value(DeckId::A),
                    "B": self.position_value(DeckId::B),
                }
            });
            events.push(self.make_event(event::DECK_POSITION, data));
        }

        if self.meters_enabled && self.now_ms >= self.next_meters_ms {
            self.next_meters_ms = self.now_ms + self.meters_interval_ms;
            let data = self.meters_value();
            events.push(self.make_event(event::METERS, data));
        }
        events
    }

    // ---------------------------------------------------------------- ディスパッチ

    pub fn handle(&mut self, op_name: &str, params: &Value) -> Handled {
        let result: OpResult = match op_name {
            op::ENGINE_PING => Ok((
                json!({ "engineTimeMs": self.now_ms, "rev": self.rev }),
                Vec::new(),
            )),
            op::STATE_SNAPSHOT => Ok((self.snapshot(), Vec::new())),
            op::DECK_LOAD => self.op_deck_load(params),
            op::DECK_UNLOAD => self.op_deck_unload(params),
            op::DECK_PLAY => self.op_deck_transport(params, true),
            op::DECK_PAUSE => self.op_deck_transport(params, false),
            op::DECK_SEEK => self.op_deck_seek(params),
            op::DECK_TEMPO_SET => self.op_deck_tempo(params),
            op::DECK_KEYLOCK_SET => self.op_deck_keylock(params),
            op::DECK_SYNC_SET => self.op_deck_sync(params),
            op::DECK_HOTCUE_SET => self.op_hotcue_set(params),
            op::DECK_HOTCUE_JUMP => self.op_hotcue_jump(params),
            op::DECK_HOTCUE_CLEAR => self.op_hotcue_clear(params),
            op::DECK_LOOP_SET => self.op_loop_set(params),
            op::DECK_LOOP_ENABLE => self.op_loop_enable(params),
            op::MIXER_CHANNEL_GAIN => self.op_channel_gain(params),
            op::MIXER_CHANNEL_EQ => self.op_channel_eq(params),
            op::MIXER_CHANNEL_PFL => self.op_channel_pfl(params),
            op::MIXER_CROSSFADER => self.op_crossfader(params),
            op::MIXER_MASTER_GAIN => self.op_master_gain(params),
            op::AUDIO_DEVICES_LIST => Ok((self.audio_devices_value(), Vec::new())),
            op::AUDIO_CONFIG_GET => Ok((
                serde_json::to_value(&self.audio).unwrap_or(Value::Null),
                Vec::new(),
            )),
            op::AUDIO_CONFIG_SET => self.op_audio_config_set(params),
            op::METERS_SUBSCRIBE => self.op_meters_subscribe(params),
            op::SIM_ADVANCE_TIME => self.op_sim_advance_time(params),
            op::SESSION_HELLO => Err(ProtocolError::new(
                ErrorCode::UnsupportedOperation,
                "session.hello はランタイムが処理します",
            )),
            unknown => Err(ProtocolError::new(
                ErrorCode::UnknownOp,
                format!("未知の操作: {unknown}"),
            )),
        };

        match result {
            Ok((data, events)) => Handled {
                outcome: Ok(data),
                events,
            },
            Err(error) => Handled {
                outcome: Err(error),
                events: Vec::new(),
            },
        }
    }

    // ---------------------------------------------------------------- デッキ操作

    fn op_deck_load(&mut self, params: &Value) -> OpResult {
        let parsed: LoadParams = parse_params(params)?;
        let deck_id = resolve_deck(&parsed.deck)?;
        let descriptor = parsed.track;

        if descriptor.track_id.trim().is_empty() {
            return Err(ProtocolError::invalid_params("track.trackId が空です"));
        }
        if descriptor.path.trim().is_empty() {
            return Err(ProtocolError::invalid_params("track.path が空です"));
        }
        let duration_ms = finite(descriptor.duration_ms, "track.durationMs")?;
        if duration_ms <= 0.0 {
            return Err(ProtocolError::invalid_params(
                "track.durationMs は正の値である必要があります",
            ));
        }
        if let Some(bpm) = descriptor.bpm {
            in_range(bpm, 20.0, 300.0, "track.bpm")?;
        }
        let sample_rate_hz = descriptor.sample_rate_hz.unwrap_or(44_100);
        if !(8_000..=384_000).contains(&sample_rate_hz) {
            return Err(ProtocolError::invalid_params(
                "track.sampleRateHz が想定範囲外です",
            ));
        }
        let channels = descriptor.channels.unwrap_or(2);
        if channels == 0 || channels > 8 {
            return Err(ProtocolError::invalid_params("track.channels が不正です"));
        }
        let beatgrid_offset_ms = finite(
            descriptor.beatgrid_offset_ms.unwrap_or(0.0),
            "track.beatgridOffsetMs",
        )?;
        let latency = match parsed.simulate_load_latency_ms {
            Some(value) => in_range(value, 0.0, 60_000.0, "simulateLoadLatencyMs")?,
            None => self.config.load_latency_ms,
        };

        let track = LoadedTrack {
            track_id: descriptor.track_id,
            path: descriptor.path,
            title: descriptor.title,
            artist: descriptor.artist,
            duration_ms,
            bpm: descriptor.bpm,
            sample_rate_hz,
            channels,
            beatgrid_offset_ms,
        };

        self.next_load_id += 1;
        let load_id = self.next_load_id;
        self.rev += 1;
        {
            let deck = self.deck_mut(deck_id);
            deck.status = DeckStatus::Loading;
            deck.track = None;
            deck.position_ms = 0.0;
            deck.loop_region = None;
            deck.hot_cues = [None; HOT_CUE_SLOTS];
            deck.last_error = None;
            deck.load_id = Some(load_id);
            deck.refresh_derived();
        }
        self.pending_loads.push(PendingLoad {
            deck: deck_id,
            load_id,
            ready_at_ms: self.now_ms + latency,
            fail: parsed.simulate_load_failure,
            track,
        });

        let event = self.deck_state_event(deck_id);
        Ok((
            json!({
                "accepted": true,
                "deck": deck_id,
                "loadId": load_id,
                "readyAtMs": self.now_ms + latency,
            }),
            vec![event],
        ))
    }

    fn op_deck_unload(&mut self, params: &Value) -> OpResult {
        let parsed: DeckParams = parse_params(params)?;
        let deck_id = resolve_deck(&parsed.deck)?;
        self.rev += 1;
        {
            let deck = self.deck_mut(deck_id);
            *deck = DeckState::new(deck_id);
        }
        self.pending_loads.retain(|pending| pending.deck != deck_id);
        let event = self.deck_state_event(deck_id);
        Ok((json!({ "deck": deck_id }), vec![event]))
    }

    fn op_deck_transport(&mut self, params: &Value, play: bool) -> OpResult {
        let parsed: DeckParams = parse_params(params)?;
        let deck_id = resolve_deck(&parsed.deck)?;
        {
            let deck = self.deck(deck_id);
            match deck.status {
                DeckStatus::Empty | DeckStatus::Error => {
                    return Err(ProtocolError::new(
                        ErrorCode::NoTrackLoaded,
                        format!("デッキ {deck_id} に曲がロードされていません"),
                    ))
                }
                DeckStatus::Loading => {
                    return Err(ProtocolError::new(
                        ErrorCode::TrackNotReady,
                        format!("デッキ {deck_id} はロード中です"),
                    ))
                }
                _ => {}
            }
        }
        self.rev += 1;
        {
            let deck = self.deck_mut(deck_id);
            deck.status = if play {
                DeckStatus::Playing
            } else {
                DeckStatus::Paused
            };
        }
        // 再生開始直後に位置通知が出るようにする。
        if play {
            self.next_position_ms = self.now_ms;
        }
        let event = self.deck_state_event(deck_id);
        Ok((
            json!({ "deck": deck_id, "status": if play { "playing" } else { "paused" } }),
            vec![event],
        ))
    }

    fn op_deck_seek(&mut self, params: &Value) -> OpResult {
        let parsed: SeekParams = parse_params(params)?;
        let deck_id = resolve_deck(&parsed.deck)?;
        let duration = self.require_loaded(deck_id)?;
        let position = in_range(parsed.position_ms, 0.0, duration, "positionMs")?;
        self.rev += 1;
        {
            let deck = self.deck_mut(deck_id);
            deck.position_ms = position;
            deck.refresh_derived();
        }
        let event = self.deck_state_event(deck_id);
        Ok((
            json!({ "deck": deck_id, "positionMs": position }),
            vec![event],
        ))
    }

    fn op_deck_tempo(&mut self, params: &Value) -> OpResult {
        let parsed: TempoParams = parse_params(params)?;
        let deck_id = resolve_deck(&parsed.deck)?;
        let rate = in_range(parsed.rate, RATE_MIN, RATE_MAX, "rate")?;
        self.rev += 1;
        {
            let deck = self.deck_mut(deck_id);
            deck.rate = rate;
            // 手動でテンポを動かしたら SYNC は外れる（実機の挙動に合わせた既定）。
            deck.sync_enabled = false;
            deck.sync_leader = None;
            deck.refresh_derived();
        }
        let event = self.deck_state_event(deck_id);
        Ok((json!({ "deck": deck_id, "rate": rate }), vec![event]))
    }

    fn op_deck_keylock(&mut self, params: &Value) -> OpResult {
        let parsed: EnableParams = parse_params(params)?;
        let deck_id = resolve_deck(&parsed.deck)?;
        self.rev += 1;
        self.deck_mut(deck_id).keylock = parsed.enabled;
        let event = self.deck_state_event(deck_id);
        Ok((
            json!({ "deck": deck_id, "keylock": parsed.enabled }),
            vec![event],
        ))
    }

    /// SYNC のプレースホルダ。BPM 比でレートを合わせるだけで、
    /// **ビート位相の整合は行わない**。実エンジン置き換え時の差し替え点。
    fn op_deck_sync(&mut self, params: &Value) -> OpResult {
        let parsed: SyncParams = parse_params(params)?;
        let deck_id = resolve_deck(&parsed.deck)?;
        let leader_id = match parsed.leader.as_deref() {
            Some(raw) => Some(resolve_deck(raw)?),
            None => DeckId::ALL.iter().copied().find(|id| *id != deck_id),
        };
        self.require_loaded(deck_id)?;

        let mut applied_rate: Option<f64> = None;
        if parsed.enabled {
            if let Some(leader) = leader_id {
                let leader_bpm = self.deck(leader).track.as_ref().and_then(|t| t.bpm);
                let follower_bpm = self.deck(deck_id).track.as_ref().and_then(|t| t.bpm);
                if let (Some(leader_bpm), Some(follower_bpm)) = (leader_bpm, follower_bpm) {
                    if follower_bpm > 0.0 {
                        let rate = (leader_bpm / follower_bpm).clamp(RATE_MIN, RATE_MAX);
                        applied_rate = Some(rate);
                    }
                }
            }
        }

        self.rev += 1;
        {
            let deck = self.deck_mut(deck_id);
            deck.sync_enabled = parsed.enabled;
            deck.sync_leader = if parsed.enabled { leader_id } else { None };
            if let Some(rate) = applied_rate {
                deck.rate = rate;
            }
            deck.refresh_derived();
        }
        let event = self.deck_state_event(deck_id);
        Ok((
            json!({
                "deck": deck_id,
                "enabled": parsed.enabled,
                "leader": leader_id,
                "rate": self.deck(deck_id).rate,
                "phaseAligned": false,
            }),
            vec![event],
        ))
    }

    fn op_hotcue_set(&mut self, params: &Value) -> OpResult {
        let parsed: HotcueParams = parse_params(params)?;
        let deck_id = resolve_deck(&parsed.deck)?;
        let duration = self.require_loaded(deck_id)?;
        let slot = resolve_hotcue_slot(parsed.index)?;
        let position = match parsed.position_ms {
            Some(value) => in_range(value, 0.0, duration, "positionMs")?,
            None => self.deck(deck_id).position_ms,
        };
        self.rev += 1;
        self.deck_mut(deck_id).hot_cues[slot] = Some(position);
        let event = self.deck_state_event(deck_id);
        Ok((
            json!({ "deck": deck_id, "index": parsed.index, "positionMs": position }),
            vec![event],
        ))
    }

    fn op_hotcue_jump(&mut self, params: &Value) -> OpResult {
        let parsed: HotcueParams = parse_params(params)?;
        let deck_id = resolve_deck(&parsed.deck)?;
        self.require_loaded(deck_id)?;
        let slot = resolve_hotcue_slot(parsed.index)?;
        let position = self.deck(deck_id).hot_cues[slot].ok_or_else(|| {
            ProtocolError::invalid_params(format!(
                "デッキ {deck_id} のホットキュー {} は未設定です",
                parsed.index
            ))
        })?;
        self.rev += 1;
        {
            let deck = self.deck_mut(deck_id);
            deck.position_ms = position;
            deck.refresh_derived();
        }
        let event = self.deck_state_event(deck_id);
        Ok((
            json!({ "deck": deck_id, "index": parsed.index, "positionMs": position }),
            vec![event],
        ))
    }

    fn op_hotcue_clear(&mut self, params: &Value) -> OpResult {
        let parsed: HotcueParams = parse_params(params)?;
        let deck_id = resolve_deck(&parsed.deck)?;
        let slot = resolve_hotcue_slot(parsed.index)?;
        self.rev += 1;
        self.deck_mut(deck_id).hot_cues[slot] = None;
        let event = self.deck_state_event(deck_id);
        Ok((
            json!({ "deck": deck_id, "index": parsed.index }),
            vec![event],
        ))
    }

    fn op_loop_set(&mut self, params: &Value) -> OpResult {
        let parsed: LoopSetParams = parse_params(params)?;
        let deck_id = resolve_deck(&parsed.deck)?;
        let duration = self.require_loaded(deck_id)?;
        let start = in_range(parsed.start_ms, 0.0, duration, "startMs")?;
        let end = in_range(parsed.end_ms, 0.0, duration, "endMs")?;
        if end <= start {
            return Err(ProtocolError::invalid_params(
                "endMs は startMs より大きい必要があります",
            ));
        }
        self.rev += 1;
        self.deck_mut(deck_id).loop_region = Some(LoopRegion {
            start_ms: start,
            end_ms: end,
            enabled: true,
        });
        let event = self.deck_state_event(deck_id);
        Ok((
            json!({ "deck": deck_id, "startMs": start, "endMs": end, "enabled": true }),
            vec![event],
        ))
    }

    fn op_loop_enable(&mut self, params: &Value) -> OpResult {
        let parsed: EnableParams = parse_params(params)?;
        let deck_id = resolve_deck(&parsed.deck)?;
        let region = self.deck(deck_id).loop_region.ok_or_else(|| {
            ProtocolError::invalid_params(format!("デッキ {deck_id} にループが未設定です"))
        })?;
        self.rev += 1;
        self.deck_mut(deck_id).loop_region = Some(LoopRegion {
            enabled: parsed.enabled,
            ..region
        });
        let event = self.deck_state_event(deck_id);
        Ok((
            json!({ "deck": deck_id, "enabled": parsed.enabled }),
            vec![event],
        ))
    }

    // ---------------------------------------------------------------- ミキサー

    fn op_channel_gain(&mut self, params: &Value) -> OpResult {
        let parsed: GainParams = parse_params(params)?;
        let deck_id = resolve_deck(&parsed.deck)?;
        let gain = in_range(parsed.gain, 0.0, 1.0, "gain")?;
        self.rev += 1;
        self.channel_mut(deck_id).gain = gain;
        let event = self.mixer_state_event();
        Ok((json!({ "deck": deck_id, "gain": gain }), vec![event]))
    }

    fn op_channel_eq(&mut self, params: &Value) -> OpResult {
        let parsed: EqParams = parse_params(params)?;
        let deck_id = resolve_deck(&parsed.deck)?;
        let gain = in_range(parsed.gain, EQ_GAIN_MIN, EQ_GAIN_MAX, "gain")?;
        // 状態を触る前にバンド名を検証する。失敗した操作で rev を進めない。
        if !matches!(parsed.band.as_str(), "low" | "mid" | "high") {
            return Err(ProtocolError::invalid_params(format!(
                "band は low / mid / high のいずれかです（受信値: {}）",
                parsed.band
            )));
        }
        self.rev += 1;
        {
            let channel = self.channel_mut(deck_id);
            match parsed.band.as_str() {
                "low" => channel.eq_low = gain,
                "mid" => channel.eq_mid = gain,
                _ => channel.eq_high = gain,
            }
        }
        let event = self.mixer_state_event();
        Ok((
            json!({ "deck": deck_id, "band": parsed.band, "gain": gain }),
            vec![event],
        ))
    }

    fn op_channel_pfl(&mut self, params: &Value) -> OpResult {
        let parsed: PflParams = parse_params(params)?;
        let deck_id = resolve_deck(&parsed.deck)?;
        self.rev += 1;
        self.channel_mut(deck_id).pfl = parsed.enabled;
        let event = self.mixer_state_event();
        Ok((
            json!({ "deck": deck_id, "pfl": parsed.enabled }),
            vec![event],
        ))
    }

    fn op_crossfader(&mut self, params: &Value) -> OpResult {
        let parsed: CrossfaderParams = parse_params(params)?;
        let position = in_range(parsed.position, -1.0, 1.0, "position")?;
        self.rev += 1;
        self.mixer.crossfader = position;
        let event = self.mixer_state_event();
        Ok((json!({ "position": position }), vec![event]))
    }

    fn op_master_gain(&mut self, params: &Value) -> OpResult {
        let parsed: MasterGainParams = parse_params(params)?;
        let gain = in_range(parsed.gain, 0.0, 1.0, "gain")?;
        self.rev += 1;
        self.mixer.master_gain = gain;
        let event = self.mixer_state_event();
        Ok((json!({ "gain": gain }), vec![event]))
    }

    // ---------------------------------------------------------------- 音声設定

    fn audio_devices_value(&self) -> Value {
        // 実デバイスは列挙しない。実機確認前に確定させないための固定リスト。
        json!({
            "simulated": true,
            "devices": [
                {
                    "id": "sim:null-output",
                    "name": "Simulated Null Output",
                    "maxOutputChannels": 4,
                    "defaultSampleRateHz": 44100,
                    "simulated": true
                },
                {
                    "id": "sim:four-channel",
                    "name": "Simulated 4ch Interface",
                    "maxOutputChannels": 4,
                    "defaultSampleRateHz": 48000,
                    "simulated": true
                }
            ]
        })
    }

    fn op_audio_config_set(&mut self, params: &Value) -> OpResult {
        let parsed: AudioConfigParams = parse_params(params)?;
        let sample_rate_hz = parsed.sample_rate_hz.unwrap_or(self.audio.sample_rate_hz);
        if !(8_000..=384_000).contains(&sample_rate_hz) {
            return Err(ProtocolError::invalid_params(
                "sampleRateHz が想定範囲外です",
            ));
        }
        let buffer_frames = parsed.buffer_frames.unwrap_or(self.audio.buffer_frames);
        if !(16..=8_192).contains(&buffer_frames) {
            return Err(ProtocolError::invalid_params(
                "bufferFrames が想定範囲外です",
            ));
        }
        let master_channels = parsed.master_channels.unwrap_or(self.audio.master_channels);
        let pfl_channels = parsed.pfl_channels.unwrap_or(self.audio.pfl_channels);
        if master_channels[0] == master_channels[1] || pfl_channels[0] == pfl_channels[1] {
            return Err(ProtocolError::invalid_params(
                "左右に同じチャンネル番号は指定できません",
            ));
        }
        if master_channels
            .iter()
            .any(|channel| pfl_channels.contains(channel))
        {
            return Err(ProtocolError::invalid_params(
                "マスターと PFL に同じチャンネル番号は指定できません",
            ));
        }

        self.rev += 1;
        if let Some(device_id) = parsed.device_id {
            self.audio.device_id = Some(device_id);
        }
        self.audio.sample_rate_hz = sample_rate_hz;
        self.audio.buffer_frames = buffer_frames;
        self.audio.master_channels = master_channels;
        self.audio.pfl_channels = pfl_channels;
        // シミュレータはデバイスを開かないので applied は常に false のまま。
        self.audio.applied = false;

        let data = serde_json::to_value(&self.audio).unwrap_or(Value::Null);
        let event = self.make_event(event::AUDIO_CONFIG, data.clone());
        Ok((data, vec![event]))
    }

    fn op_meters_subscribe(&mut self, params: &Value) -> OpResult {
        let parsed: MetersParams = parse_params(params)?;
        let interval = match parsed.interval_ms {
            Some(value) => in_range(value, 20.0, 2_000.0, "intervalMs")?,
            None => self.config.meters_interval_ms,
        };
        self.rev += 1;
        self.meters_enabled = parsed.enabled;
        self.meters_interval_ms = interval;
        self.next_meters_ms = self.now_ms;
        Ok((
            json!({ "enabled": parsed.enabled, "intervalMs": interval, "simulated": true }),
            Vec::new(),
        ))
    }

    fn op_sim_advance_time(&mut self, params: &Value) -> OpResult {
        if !self.config.deterministic {
            return Err(ProtocolError::new(
                ErrorCode::UnsupportedOperation,
                "sim.advanceTime は --deterministic 起動時のみ利用できます",
            ));
        }
        let parsed: AdvanceParams = parse_params(params)?;
        let delta = in_range(parsed.ms, 0.0, 24.0 * 60.0 * 60.0 * 1000.0, "ms")?;
        let events = self.tick(self.now_ms + delta);
        Ok((json!({ "engineTimeMs": self.now_ms }), events))
    }

    // ---------------------------------------------------------------- 状態

    pub fn snapshot(&self) -> Value {
        json!({
            "rev": self.rev,
            "seq": self.seq,
            "engineId": self.config.engine_id,
            "sessionId": self.session_id,
            "engineTimeMs": self.now_ms,
            "engine": self.info(),
            "decks": {
                "A": self.deck(DeckId::A),
                "B": self.deck(DeckId::B),
            },
            "mixer": self.mixer_value(),
            "audio": &self.audio,
            "meters": {
                "enabled": self.meters_enabled,
                "intervalMs": self.meters_interval_ms,
                "simulated": true,
            },
        })
    }

    fn mixer_value(&self) -> Value {
        json!({
            "crossfader": self.mixer.crossfader,
            "masterGain": self.mixer.master_gain,
            "headphoneGain": self.mixer.headphone_gain,
            "headphoneMix": self.mixer.headphone_mix,
            "channels": {
                "A": &self.mixer.channels[0],
                "B": &self.mixer.channels[1],
            },
        })
    }

    fn position_value(&self, deck_id: DeckId) -> Value {
        let deck = self.deck(deck_id);
        json!({
            "positionMs": deck.position_ms,
            "positionFrames": deck.position_frames,
            "durationMs": deck.duration_ms(),
            "sampleRateHz": deck.sample_rate(),
            "rate": deck.rate,
            "status": deck.status,
        })
    }

    /// シミュレートされたメーター値。実音声の測定値ではない。
    fn meters_value(&self) -> Value {
        let mut channels = serde_json::Map::new();
        let mut master_peak: f64 = 0.0;
        for (index, deck_id) in DeckId::ALL.iter().enumerate() {
            let deck = self.deck(*deck_id);
            let channel = &self.mixer.channels[index];
            let envelope = if deck.status == DeckStatus::Playing {
                0.55 + 0.35 * (deck.position_ms / 500.0).sin().abs()
            } else {
                0.0
            };
            let peak = (envelope * channel.gain).clamp(0.0, 1.0);
            master_peak = master_peak.max(peak * self.mixer.master_gain);
            channels.insert(
                deck_id.as_str().to_string(),
                json!({ "peak": peak, "rms": peak * 0.7, "pfl": channel.pfl }),
            );
        }
        json!({
            "simulated": true,
            "master": { "peak": master_peak, "rms": master_peak * 0.7 },
            "channels": Value::Object(channels),
        })
    }

    // ---------------------------------------------------------------- 内部ヘルパ

    fn index(deck_id: DeckId) -> usize {
        match deck_id {
            DeckId::A => 0,
            DeckId::B => 1,
        }
    }

    fn deck(&self, deck_id: DeckId) -> &DeckState {
        &self.decks[Self::index(deck_id)]
    }

    fn deck_mut(&mut self, deck_id: DeckId) -> &mut DeckState {
        &mut self.decks[Self::index(deck_id)]
    }

    fn channel_mut(&mut self, deck_id: DeckId) -> &mut ChannelState {
        &mut self.mixer.channels[Self::index(deck_id)]
    }

    /// 曲がロード済みであることを確認し、長さ（ミリ秒）を返す。
    fn require_loaded(&self, deck_id: DeckId) -> Result<f64, ProtocolError> {
        let deck = self.deck(deck_id);
        match deck.status {
            DeckStatus::Loading => Err(ProtocolError::new(
                ErrorCode::TrackNotReady,
                format!("デッキ {deck_id} はロード中です"),
            )),
            DeckStatus::Empty | DeckStatus::Error => Err(ProtocolError::new(
                ErrorCode::NoTrackLoaded,
                format!("デッキ {deck_id} に曲がロードされていません"),
            )),
            _ => Ok(deck.duration_ms()),
        }
    }

    fn make_event(&mut self, name: &str, data: Value) -> EventMessage {
        self.seq += 1;
        EventMessage {
            protocol: PROTOCOL_VERSION,
            engine_id: self.config.engine_id.clone(),
            event: name.to_string(),
            seq: self.seq,
            rev: self.rev,
            data,
            engine_time_ms: self.now_ms,
        }
    }

    fn deck_state_event(&mut self, deck_id: DeckId) -> EventMessage {
        let data = serde_json::to_value(self.deck(deck_id)).unwrap_or(Value::Null);
        self.make_event(event::DECK_STATE, data)
    }

    fn mixer_state_event(&mut self) -> EventMessage {
        let data = self.mixer_value();
        self.make_event(event::MIXER_STATE, data)
    }
}

type OpResult = Result<(Value, Vec<EventMessage>), ProtocolError>;

fn resolve_deck(raw: &str) -> Result<DeckId, ProtocolError> {
    DeckId::parse(raw).ok_or_else(|| ProtocolError::deck_not_found(raw))
}

fn resolve_hotcue_slot(index: u8) -> Result<usize, ProtocolError> {
    let slot = index as usize;
    if slot >= HOT_CUE_SLOTS {
        return Err(ProtocolError::invalid_params(format!(
            "index は 0 以上 {} 未満である必要があります",
            HOT_CUE_SLOTS
        )));
    }
    Ok(slot)
}

// ---------------------------------------------------------------- パラメータ型

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
struct DeckParams {
    deck: String,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
struct SeekParams {
    deck: String,
    position_ms: f64,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
struct TempoParams {
    deck: String,
    rate: f64,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
struct EnableParams {
    deck: String,
    enabled: bool,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
struct SyncParams {
    deck: String,
    enabled: bool,
    #[serde(default)]
    leader: Option<String>,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
struct HotcueParams {
    deck: String,
    index: u8,
    #[serde(default)]
    position_ms: Option<f64>,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
struct LoopSetParams {
    deck: String,
    start_ms: f64,
    end_ms: f64,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
struct GainParams {
    deck: String,
    gain: f64,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
struct EqParams {
    deck: String,
    band: String,
    gain: f64,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
struct PflParams {
    deck: String,
    enabled: bool,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
struct CrossfaderParams {
    position: f64,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
struct MasterGainParams {
    gain: f64,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
struct MetersParams {
    enabled: bool,
    #[serde(default)]
    interval_ms: Option<f64>,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
struct AdvanceParams {
    ms: f64,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
struct AudioConfigParams {
    #[serde(default)]
    device_id: Option<String>,
    #[serde(default)]
    sample_rate_hz: Option<u32>,
    #[serde(default)]
    buffer_frames: Option<u32>,
    #[serde(default)]
    master_channels: Option<[u16; 2]>,
    #[serde(default)]
    pfl_channels: Option<[u16; 2]>,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
struct LoadParams {
    deck: String,
    track: TrackDescriptor,
    /// シミュレータ専用: 非同期ロード失敗経路を再現する。
    #[serde(default)]
    simulate_load_failure: bool,
    /// シミュレータ専用: ロード所要時間を上書きする。
    #[serde(default)]
    simulate_load_latency_ms: Option<f64>,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
struct TrackDescriptor {
    track_id: String,
    path: String,
    #[serde(default)]
    title: Option<String>,
    #[serde(default)]
    artist: Option<String>,
    duration_ms: f64,
    #[serde(default)]
    bpm: Option<f64>,
    #[serde(default)]
    sample_rate_hz: Option<u32>,
    #[serde(default)]
    channels: Option<u16>,
    #[serde(default)]
    beatgrid_offset_ms: Option<f64>,
}
