//! DDJ-1000 display interoperability. Protocol observations are documented in
//! the DDJ-1000 section in README.md. No captured USB streams are replayed.
use serde::{Deserialize, Serialize};
use std::{
    sync::{Arc, Mutex},
    time::{Duration, Instant},
};
#[derive(Clone, Debug, Default, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct DeckDisplay {
    pub token: String,
    pub position_ms: f64,
    pub duration_ms: f64,
    pub bpm: f64,
    pub rate: f64,
    pub playing: bool,
    pub master: bool,
    pub beats: Vec<f64>,
    pub cues: Vec<Option<f64>>,
    pub waveform: Vec<u8>,
    pub artwork: Vec<u8>,
    pub asset_version: u32,
}
#[derive(Clone, Debug, Default, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct DisplayStatus {
    pub midi_open: bool,
    pub hid_open: bool,
    pub authenticated: bool,
    pub reports_sent: u64,
    pub heartbeat_gap_ms: u64,
    pub state_reports_per_second: u64,
    pub frame_age_ms: u64,
    pub error: Option<String>,
}
struct Shared {
    lease: Option<Instant>,
    updated: Instant,
    decks: Arc<Vec<DeckDisplay>>,
    status: DisplayStatus,
}
pub struct JogDisplay {
    shared: Arc<Mutex<Shared>>,
}
impl JogDisplay {
    pub fn new() -> Self {
        let shared = Arc::new(Mutex::new(Shared {
            lease: None,
            updated: Instant::now(),
            decks: Arc::new(vec![]),
            status: DisplayStatus::default(),
        }));
        #[cfg(target_os = "macos")]
        {
            let state = shared.clone();
            std::thread::spawn(move || mac::worker(state));
        }
        Self { shared }
    }
    pub fn lease(&self, enabled: bool) {
        self.shared.lock().unwrap().lease = enabled.then(Instant::now);
    }
    pub fn status(&self) -> DisplayStatus {
        self.shared.lock().unwrap().status.clone()
    }
    pub fn update(&self, decks: Vec<DeckDisplay>) -> Result<(), String> {
        if decks.len() != 4
            || decks.iter().any(|d| {
                d.token.len() > 256
                    || d.beats.len() > 2000
                    || d.cues.len() > 16
                    || !matches!(d.waveform.len(), 0 | 4201)
                    || d.artwork.len() > 32768
                    || [d.position_ms, d.duration_ms, d.bpm, d.rate]
                        .iter()
                        .any(|v| !v.is_finite())
                    || d.beats
                        .iter()
                        .any(|v| !v.is_finite() || *v < 0.0 || *v > 0xffffff as f64)
                    || d.cues
                        .iter()
                        .flatten()
                        .any(|v| !v.is_finite() || *v < 0.0 || *v > 0xffffff as f64)
                    || d.duration_ms < 0.0
                    || d.duration_ms > 0xffffff as f64
                    || d.bpm < 0.0
                    || d.bpm > 255.9
                    || d.rate < 0.0
                    || d.rate > 4.0
            })
        {
            return Err("Invalid DDJ-1000 display frame".into());
        }
        let mut s = self.shared.lock().unwrap();
        s.decks = Arc::new(decks);
        s.updated = Instant::now();
        Ok(())
    }
}
const HEADER: &[u8] = &[0xf0, 0, 0x40, 5, 0, 0, 2, 0, 0];
fn sysex(payload: &[u8]) -> Vec<u8> {
    [HEADER, payload, &[0xf7]].concat()
}
fn tlv(tag: u8, body: &[u8]) -> Vec<u8> {
    [&[tag, (body.len() + 2) as u8][..], body].concat()
}
fn spread(bytes: &[u8]) -> Vec<u8> {
    bytes.iter().flat_map(|b| [b >> 4, b & 15]).collect()
}
fn hash(bytes: &[u8]) -> u32 {
    bytes.iter().fold(0x811c9dc5u32, |h, b| {
        (h ^ *b as u32).wrapping_mul(0x01000193)
    })
}
fn identity() -> Vec<u8> {
    let body = [
        tlv(1, b"PioneerDJ"),
        tlv(2, b"rekordbox"),
        tlv(3, &spread(&[0x68, 0x72, 0xba, 0x32, 0xd4, 7, 0xc0, 0xe1])),
    ]
    .concat();
    sysex(&[vec![0x12, (body.len() + 2) as u8], body].concat())
}
fn response(msg: &[u8]) -> Option<Vec<u8>> {
    if !msg.starts_with(HEADER) || msg.last() != Some(&0xf7) || msg.len() < 12 {
        return None;
    }
    if msg[9..11] == [0x11, 2] {
        return Some(identity());
    }
    if msg[9] != 0x13 {
        return None;
    }
    let mut at = 11;
    while at + 2 <= msg.len() - 1 {
        let len = msg[at + 1] as usize;
        if len < 2 || at + len > msg.len() - 1 {
            return None;
        }
        if msg[at] == 3 {
            let n = &msg[at + 2..at + len];
            if n.len() < 8 || n[..8].iter().any(|b| *b > 15) {
                return None;
            }
            let seed = u32::from_be_bytes([
                n[0] * 16 + n[1],
                n[2] * 16 + n[3],
                n[4] * 16 + n[5],
                n[6] * 16 + n[7],
            ]);
            let digest = hash(&[seed.to_be_bytes(), (seed ^ 0x680131fb).to_be_bytes()].concat());
            let device = spread(&[0x87, 0xa0, 0x8e, 0xea, 0xc0, 0x90, 0x34, 0x76, 0x0b, 0x90]);
            let body = [
                tlv(1, b"PioneerDJ"),
                tlv(2, b"rekordbox"),
                tlv(4, &spread(&digest.to_be_bytes())),
                tlv(5, &device),
            ]
            .concat();
            return Some(sysex(&[vec![0x14, (body.len() + 2) as u8], body].concat()));
        }
        at += len;
    }
    None
}
fn track_id(d: &DeckDisplay) -> u32 {
    if d.token.is_empty() {
        0
    } else {
        0x03000000 | (hash(d.token.as_bytes()) & 0xffffff)
    }
}
fn u24(out: &mut [u8], value: f64) {
    out[..3].copy_from_slice(&(value.max(0.0).min(0xffffff as f64) as u32).to_le_bytes()[..3]);
}
fn record(ch: usize, d: &DeckDisplay, elapsed: f64, ready: bool) -> [u8; 64] {
    let mut b = [0; 64];
    b[0] = (ch as u8 + 1) * 16;
    b[1] = 0x21;
    b[2] = 0x18;
    b[3] = 2;
    b[4] = 0x11;
    // 0x81 is the established display-session flag in the working trace.
    // Do not clear its high bit based on software sync-master state.
    b[5] = 0x81;
    b[61] = 0x0d;
    if d.token.is_empty() {
        b[9] = 0x10;
        return b;
    }
    b[9] = 0xb4;
    let ms = (d.position_ms
        + if d.playing {
            elapsed * d.rate * 1000.0
        } else {
            0.0
        })
    .max(0.0)
    .min(d.duration_ms) as u32;
    b[11] = ((ms / 60000).min(127)) as u8;
    b[12] = ((ms / 1000) % 60) as u8;
    b[13..15].copy_from_slice(&((ms % 1000) as u16).to_le_bytes());
    b[15..19].copy_from_slice(&track_id(d).to_le_bytes());
    let tenths = (d.bpm * 10.0).round().min(2559.0) as u16;
    b[21] = (tenths / 10) as u8;
    b[38] = b[21];
    b[22] = ((tenths % 10) as u8) << 4;
    b[39] = b[22];
    b[27] = 0x80;
    u24(
        &mut b[31..34],
        d.cues
            .iter()
            .flatten()
            .next()
            .copied()
            .or(d.beats.first().copied())
            .unwrap_or(0.0),
    );
    let marker = [b[31], b[32], b[33]];
    b[55..58].copy_from_slice(&marker);
    b[58] = if ready { 3 } else { 1 };
    b[59] = if ready { 0x16 } else { 0 };
    b
}
fn transfer(ch: usize, command: u8, payload: &[u8], prime: bool) -> Vec<[u8; 64]> {
    let chunks: Vec<_> = payload.chunks(58).collect();
    let count = chunks.len().max(1);
    let mut out = Vec::new();
    let indices: Vec<_> = if prime {
        std::iter::once(count - 1).chain(0..count).collect()
    } else {
        (0..count).collect()
    };
    for i in indices {
        let mut b = [0; 64];
        b[0] = (ch as u8 + 1) * 16;
        b[1] = command;
        b[2..4].copy_from_slice(&((i + 1) as u16).to_le_bytes());
        b[4..6].copy_from_slice(&(count as u16).to_le_bytes());
        if let Some(c) = chunks.get(i) {
            b[6..6 + c.len()].copy_from_slice(c);
        }
        out.push(b);
    }
    out
}
fn load_reports(ch: usize, d: &DeckDisplay) -> Vec<[u8; 64]> {
    let mut out = transfer(ch, 0x30, &[0; 116], false);
    out.extend(transfer(ch, 0x2c, &vec![0; 4201], false));
    if d.token.is_empty() {
        return out;
    }
    let mut grid = (d.beats.len() as u16).to_le_bytes().to_vec();
    for (i, beat) in d.beats.iter().enumerate() {
        let mut b = [0; 4];
        b[0] = (i % 4 + 1) as u8;
        u24(&mut b[1..], *beat);
        grid.extend(b);
    }
    out.extend(transfer(ch, 0x2f, &[0; 58], false));
    out.extend(transfer(ch, 0x2f, &grid, false));
    let mut track = track_id(d).to_le_bytes().to_vec();
    for ms in d.cues.iter().flatten().take(16) {
        let ms = *ms as u32;
        track.extend([
            1,
            0x16,
            (ms / 60000).min(127) as u8,
            ((ms / 1000) % 60) as u8,
            (ms % 1000) as u8,
            ((ms % 1000) >> 8) as u8,
        ]);
    }
    track.resize(116, 0);
    out.extend(transfer(ch, 0x30, &track, true));
    out.extend(transfer(ch, 0x2d, &[0; 60], false));
    if !d.artwork.is_empty() {
        let art = [
            (d.artwork.len() as u16).to_le_bytes().to_vec(),
            d.artwork.clone(),
        ]
        .concat();
        out.extend(transfer(ch, 0x2b, &art, false));
    }
    if !d.waveform.is_empty() {
        out.extend(transfer(ch, 0x2c, &d.waveform, false));
    }
    out.extend(transfer(ch, 0x30, &track, true));
    out
}
enum DisplayWrite {
    Hid([u8; 64]),
    Midi(Vec<u8>),
}
fn load_jobs(ch: usize, deck: &DeckDisplay) -> Vec<DisplayWrite> {
    let mut jobs = Vec::new();
    let mut announced = false;
    for packet in load_reports(ch, deck) {
        if !announced && packet[1] == 0x2f {
            let id = 6400000 + (track_id(deck) & 0xffff);
            jobs.push(DisplayWrite::Midi(sysex(&[
                0, 0x0b, 0x2b, 0x68, 0, 0, 0, 0,
            ])));
            jobs.push(DisplayWrite::Midi(sysex(&[
                0,
                0x0c,
                0,
                0,
                ((id >> 21) & 127) as u8,
                ((id >> 14) & 127) as u8,
                ((id >> 7) & 127) as u8,
                (id & 127) as u8,
                0,
                0,
            ])));
            announced = true;
        }
        jobs.push(DisplayWrite::Hid(packet));
    }
    jobs
}
#[cfg(target_os = "macos")]
mod mac {
    use super::*;
    use midir::{MidiInput, MidiOutput};
    use std::{collections::VecDeque, sync::mpsc};
    fn write(h: &hidapi::HidDevice, b: &[u8; 64]) -> Result<(), String> {
        let mut data = [0; 65];
        data[1..].copy_from_slice(b);
        h.write(&data).map(|_| ()).map_err(|e| e.to_string())
    }
    pub(super) fn worker(shared: Arc<Mutex<Shared>>) {
        let mut last_scan = Instant::now() - Duration::from_secs(2);
        let mut ports = None;
        let mut hid = None;
        let mut auth = false;
        let mut ka = Instant::now();
        let mut started = Instant::now();
        let mut state_at = Instant::now();
        let mut ch = 0;

        let (tx, rx) = mpsc::sync_channel::<Vec<u8>>(64);
        let mut jobs: [VecDeque<DisplayWrite>; 4] = std::array::from_fn(|_| VecDeque::new());
        let mut keys = vec![(String::new(), 0); 4];
        let mut ready = [false; 4];
        let mut loading_since = [Instant::now(); 4];
        let mut reports = 0u64;
        let mut state_reports = 0u64;
        let mut metrics_at = Instant::now();
        let mut diagnostic_at = Instant::now();
        loop {
            if Arc::strong_count(&shared) == 1 {
                break;
            }
            std::thread::sleep(Duration::from_micros(500));
            unsafe {
                core_foundation::runloop::CFRunLoop::run_in_mode(
                    core_foundation::runloop::kCFRunLoopDefaultMode,
                    Duration::ZERO,
                    false,
                );
            }
            let (active, decks, updated) = {
                let s = shared.lock().unwrap();
                (
                    s.lease
                        .is_some_and(|t| t.elapsed() < Duration::from_secs(3)),
                    s.decks.clone(),
                    s.updated,
                )
            };
            if diagnostic_at.elapsed() >= Duration::from_secs(1) {
                diagnostic_at = Instant::now();
                let json = {
                    let mut s = shared.lock().unwrap();
                    s.status.state_reports_per_second = state_reports;
                    s.status.frame_age_ms = updated.elapsed().as_millis() as u64;
                    serde_json::to_vec(&s.status)
                };
                state_reports = 0;
                if let Ok(json) = json {
                    // A bounded, overwritten diagnostic snapshot; no track
                    // names, paths, audio, or raw MIDI content are included.
                    let _ = std::fs::write(
                        std::env::temp_dir().join("djaly-ddj-display-status.json"),
                        json,
                    );
                }
            }
            if !active {
                if let Some(h) = hid.take() {
                    for i in 0..4 {
                        let _ = write(&h, &record(i, &DeckDisplay::default(), 0.0, false));
                    }
                }
                ports = None;
                auth = false;
                jobs.iter_mut().for_each(|j| j.clear());
                keys.fill((String::new(), 0));
                ready.fill(false);
                shared.lock().unwrap().status = DisplayStatus::default();
                continue;
            }
            if ports.is_none() && last_scan.elapsed() > Duration::from_secs(1) {
                last_scan = Instant::now();
                let opened = (|| -> Result<_, String> {
                    let mut input =
                        MidiInput::new("DJaly jog handshake").map_err(|e| e.to_string())?;
                    input.ignore(midir::Ignore::None);
                    let output =
                        MidiOutput::new("DJaly jog heartbeat").map_err(|e| e.to_string())?;
                    let ins: Vec<_> = input
                        .ports()
                        .into_iter()
                        .filter(|p| input.port_name(p).is_ok_and(|n| n == "DDJ-1000"))
                        .collect();
                    let outs: Vec<_> = output
                        .ports()
                        .into_iter()
                        .filter(|p| output.port_name(p).is_ok_and(|n| n == "DDJ-1000"))
                        .collect();
                    if ins.len() != 1 || outs.len() != 1 {
                        return Err("DDJ-1000画面用MIDIポート待ち".into());
                    }
                    while rx.try_recv().is_ok() {}
                    let sender = tx.clone();
                    let ip = input
                        .connect(
                            &ins[0],
                            "DJaly jog input",
                            move |_, b, _| {
                                if b.len() <= 256 && b.first() == Some(&0xf0) {
                                    let _ = sender.try_send(b.to_vec());
                                }
                            },
                            (),
                        )
                        .map_err(|e| e.to_string())?;
                    let mut op = output
                        .connect(&outs[0], "DJaly jog output")
                        .map_err(|e| e.to_string())?;
                    let api = hidapi::HidApi::new().map_err(|e| e.to_string())?;
                    let dev = api
                        .device_list()
                        .find(|d| {
                            d.vendor_id() == 0x2b73
                                && d.product_id() == 0x20
                                && d.usage_page() == 0xffa0
                        })
                        .ok_or("DDJ-1000画面用HIDポート待ち")?;
                    let h = dev.open_device(&api).map_err(|e| e.to_string())?;
                    for body in [
                        vec![0, 0x0b, 0x2b, 0x68, 0, 0, 0],
                        [
                            vec![
                                0, 0x0a, 0, 0x28, 0, 0x26, 0, 0x0a, 0x39, 0x4a, 0x74, 0x28, 0x53,
                                0x20, 0x20, 0x14, 0x15, 0x22, 5,
                            ],
                            vec![0; 21],
                        ]
                        .concat(),
                        vec![0, 0x0b, 0x2b, 0x68, 0, 0, 0],
                        vec![0, 0x0c, 0, 0, 2, 0x0e, 0x0e, 0, 0, 0],
                    ] {
                        op.send(&sysex(&body)).map_err(|e| e.to_string())?;
                    }
                    Ok((ip, op, h))
                })();
                match opened {
                    Ok((ip, op, h)) => {
                        ports = Some((ip, op));
                        hid = Some(h);
                        auth = false;
                        started = Instant::now();
                        metrics_at = Instant::now();
                        ka = Instant::now() - Duration::from_secs(1);
                        keys.fill((String::new(), 0));
                        ready.fill(false);
                        shared.lock().unwrap().status = DisplayStatus {
                            midi_open: true,
                            hid_open: true,
                            ..Default::default()
                        };
                    }
                    Err(e) => {
                        shared.lock().unwrap().status.error = Some(e);
                        continue;
                    }
                }
            }
            let Some((_, op)) = &mut ports else { continue };
            let step = (|| -> Result<(), String> {
                if ka.elapsed() >= Duration::from_millis(200) {
                    if metrics_at.elapsed() > Duration::from_secs(1) {
                        let gap = ka.elapsed().as_millis() as u64;
                        let mut s = shared.lock().unwrap();
                        s.status.heartbeat_gap_ms = s.status.heartbeat_gap_ms.max(gap);
                    }
                    op.send(&sysex(&[0x50, 1])).map_err(|e| e.to_string())?;
                    ka = Instant::now();
                }
                for msg in rx.try_iter().take(16) {
                    if let Some(reply) = response(&msg) {
                        if msg.get(9) == Some(&0x11) {
                            auth = false;
                            started = Instant::now();
                            keys.fill((String::new(), 0));
                            ready.fill(false);
                            jobs.iter_mut().for_each(|j| j.clear());
                            shared.lock().unwrap().status.authenticated = false;
                        }
                        op.send(&reply).map_err(|e| e.to_string())?;
                    }
                    if msg == sysex(&[0x15, 2]) && !auth {
                        auth = true;
                        // Display-only activation records from the public
                        // protocol trace; no mixer/driver settings are changed.
                        for body in [
                            [
                                vec![
                                    0, 0x0a, 0, 0x28, 0, 0x26, 0, 0x24, 0x15, 0x32, 0x55, 0x48,
                                    0x14, 0x21,
                                ],
                                vec![0; 26],
                            ]
                            .concat(),
                            vec![0, 0x0b, 0x35, 0x60, 0x14, 1, 0],
                            vec![0, 0x0c, 0, 0, 2, 0x0e, 0x0e, 0, 0, 0],
                            vec![0, 0x0b, 0x31, 0, 0, 0, 0, 0],
                            [
                                vec![
                                    0, 0x0a, 0, 0x28, 0, 0x26, 0, 0x28, 0x49, 0x0a, 0x64, 0x69,
                                    0x14, 0,
                                ],
                                vec![0; 26],
                            ]
                            .concat(),
                            vec![0, 0x0b, 0x31, 0, 0, 0, 0, 0],
                            vec![0, 0x0c, 0, 0, 2, 0x0e, 0x0e, 0, 0, 0],
                        ] {
                            op.send(&sysex(&body)).map_err(|e| e.to_string())?;
                        }
                        for c in 0..4 {
                            op.send(&[0x90 + c, 0x5b, 1]).map_err(|e| e.to_string())?;
                            op.send(&[0x90 + c, 0x5d, 0]).map_err(|e| e.to_string())?;
                        }
                        shared.lock().unwrap().status.authenticated = true;
                    }
                }
                if !auth {
                    if started.elapsed() > Duration::from_secs(10) {
                        return Err("DDJ-1000の画面接続応答が10秒以内に返りませんでした".into());
                    }
                    return Ok(());
                }
                let Some(h) = &hid else { return Ok(()) };
                if decks.len() != 4 || updated.elapsed() > Duration::from_secs(3) {
                    return Ok(());
                }
                for i in 0..4 {
                    let key = (decks[i].token.clone(), decks[i].asset_version);
                    if keys[i] != key {
                        jobs[i] = load_jobs(i, &decks[i]).into();
                        ready[i] = false;
                        keys[i] = key;
                        loading_since[i] = Instant::now();
                    }
                }
                if Instant::now() >= state_at {
                    let now = Instant::now();
                    // Absolute deadlines prevent USB write time and sleeps from
                    // accumulating into a slower-than-required display clock.
                    state_at =
                        if now.saturating_duration_since(state_at) > Duration::from_millis(100) {
                            now + Duration::from_millis(8)
                        } else {
                            state_at + Duration::from_millis(8)
                        };
                    for i in 0..4 {
                        let frame = if loading_since[i].elapsed() < Duration::from_millis(30) {
                            record(i, &DeckDisplay::default(), 0.0, false)
                        } else {
                            record(i, &decks[i], updated.elapsed().as_secs_f64(), ready[i])
                        };
                        write(h, &frame)?;
                        reports += 1;
                        state_reports += 1;
                    }
                } else {
                    for offset in 0..4 {
                        let i = (ch + offset) % 4;
                        if let Some(packet) = jobs[i].pop_front() {
                            match packet {
                                DisplayWrite::Hid(packet) => {
                                    write(h, &packet)?;
                                    reports += 1;
                                }
                                DisplayWrite::Midi(message) => {
                                    op.send(&message).map_err(|e| e.to_string())?;
                                }
                            }
                            if jobs[i].is_empty() {
                                ready[i] = !decks[i].waveform.is_empty();
                            }
                            ch = (i + 1) % 4;
                            break;
                        }
                    }
                }
                shared.lock().unwrap().status.reports_sent = reports;
                Ok(())
            })();
            if let Err(e) = step {
                ports = None;
                hid = None;
                auth = false;
                jobs.iter_mut().for_each(|j| j.clear());
                let mut s = shared.lock().unwrap();
                s.status.authenticated = false;
                s.status.hid_open = false;
                s.status.midi_open = false;
                s.status.error = Some(e);
            }
        }
    }
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn bounded_reports() {
        for size in [0, 1, 58, 59, 4201] {
            let b = transfer(3, 0x2c, &vec![7; size], false);
            assert_eq!(b.len(), size.div_ceil(58).max(1));
            assert!(b.iter().all(|r| r[0] == 0x40 && r[1] == 0x2c));
        }
    }
    #[test]
    fn challenge_validation() {
        assert!(response(&[0xf0, 0xf7]).is_none());
        assert_eq!(response(&sysex(&[0x11, 2])), Some(identity()));
        let mut body = vec![0x13, 12, 3, 10];
        body.extend([1, 2, 3, 4, 5, 6, 7, 8]);
        let reply = response(&sysex(&body)).unwrap();
        assert_eq!(reply.len(), 66);
        body[4] = 16;
        assert!(response(&sysex(&body)).is_none());
    }
    #[test]
    fn time_and_unload() {
        let d = DeckDisplay {
            token: "test".into(),
            position_ms: 61542.0,
            duration_ms: 180000.0,
            bpm: 141.8,
            rate: 1.0,
            ..Default::default()
        };
        let r = record(0, &d, 0.0, true);
        assert_eq!(&r[11..15], &[1, 1, 0x1e, 2]);
        assert_eq!(&r[21..23], &[141, 0x80]);
        assert_eq!(r[58], 3);
        assert_eq!(record(0, &DeckDisplay::default(), 0.0, false)[9], 0x10);
    }
    #[test]
    #[ignore = "Uses connected DDJ-1000 MIDI/HID"]
    fn hardware_handshake() {
        let bridge = JogDisplay::new();
        for _ in 0..60 {
            bridge.lease(true);
            bridge.update(vec![DeckDisplay::default(); 4]).unwrap();
            std::thread::sleep(Duration::from_millis(200));
            if bridge.status().authenticated && bridge.status().reports_sent >= 20 {
                println!("DISPLAY {:?}", bridge.status());
                bridge.lease(false);
                return;
            }
        }
        panic!("{:?}", bridge.status());
    }
    #[test]
    fn invalid_frame_does_not_replace_previous_snapshot() {
        let bridge = JogDisplay::new();
        let mut decks = vec![DeckDisplay::default(); 4];
        decks[0].token = "original".into();
        bridge.update(decks.clone()).unwrap();
        decks[0].artwork = vec![0; 32769];
        assert!(bridge.update(decks).is_err());
        assert_eq!(bridge.shared.lock().unwrap().decks[0].token, "original");
        assert!(bridge.update(vec![]).is_err());
    }
    #[test]
    fn load_clears_old_track_before_waveform_and_finishes_with_identity() {
        let deck = DeckDisplay {
            token: "new track".into(),
            waveform: vec![0; 4201],
            beats: vec![0.0, 500.0],
            ..Default::default()
        };
        let packets = load_reports(1, &deck);
        assert_eq!(packets[0][1], 0x30);
        assert!(packets[0][6..].iter().all(|b| *b == 0));
        assert_eq!(packets.last().unwrap()[1], 0x30);
        assert!(packets.iter().all(|p| p[0] == 0x20));
        assert!(packets.iter().any(|p| p[1] == 0x2f));
        let jobs = load_jobs(1, &deck);
        let announce = jobs
            .iter()
            .position(|j| matches!(j, DisplayWrite::Midi(_)))
            .unwrap();
        assert!(matches!(&jobs[announce-1], DisplayWrite::Hid(p) if p[1]==0x2c));
        assert!(matches!(&jobs[announce+2], DisplayWrite::Hid(p) if p[1]==0x2f));
    }
}
