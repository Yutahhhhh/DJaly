//! DDJ-1000 MIDI transport. All device I/O lives on one worker, never the UI
//! or CoreMIDI callback. A renewable lease releases the device after webview loss.
use midir::{MidiInput, MidiInputConnection, MidiOutput, MidiOutputConnection};
use serde::Serialize;
use std::{
    sync::{
        mpsc::{self, SyncSender},
        Arc, Mutex,
    },
    time::{Duration, Instant},
};
use tauri::{AppHandle, State};

fn process_device_changes() {
    // CoreMIDI delivers topology changes on the thread that created its client.
    // Sleeping on the Rust channel alone leaves that thread's device list stale.
    #[cfg(target_os = "macos")]
    unsafe {
        core_foundation::runloop::CFRunLoop::run_in_mode(
            core_foundation::runloop::kCFRunLoopDefaultMode,
            Duration::ZERO,
            false,
        );
    }
}

#[derive(Clone, Debug, Default, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct MidiStatus {
    pub enabled: bool,
    pub connected: bool,
    pub generation: u64,
    pub device: Option<String>,
    pub received: u64,
    pub sent: u64,
    pub error: Option<String>,
    pub native_performance: super::performance_transport::Observation,
    pub display: super::jog_display::DisplayStatus,
}
#[derive(Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct MidiEvent {
    pub generation: u64,
    pub messages: Vec<Vec<u8>>,
    pub captured_us: Vec<u64>,
    pub driver_timestamps_us: Vec<u64>,
    pub sequences: Vec<u64>,
    pub native_performance: bool,
}
// Bounded storage in the CoreMIDI callback; Vec allocation happens on the worker.
struct CapturedPacket {generation:u64,captured_us:u64,driver_us:u64,sequence:u64,length:usize,at:Instant,bytes:[u8;1024]}
enum Request {
    Performance(super::performance_transport::Config),
    Lease(bool),
    Send(u64, Vec<Vec<u8>>),
}
pub struct MidiController {
    tx: SyncSender<Request>,
    status: Arc<Mutex<MidiStatus>>,
    inbox: Option<MidiInbox>,
}
struct MidiInbox {
    receiver: Mutex<mpsc::Receiver<MidiEvent>>,
    overflow: Arc<std::sync::atomic::AtomicBool>,
}
impl MidiInbox {
    fn read(&self) -> Result<Vec<MidiEvent>, String> {
        let receiver = self.receiver.lock().unwrap();
        if self.overflow.swap(false, std::sync::atomic::Ordering::SeqCst) {
            while receiver.try_recv().is_ok() {}
            return Err("MIDI受信キューが上限を超えました。操作を解除して再接続します".into());
        }
        Ok(receiver.try_iter().take(16).collect())
    }
}
fn supported(name: &str) -> bool {
    // Never open an SRT or another Pioneer device with this model's mapping.
    let name = name.trim().to_ascii_uppercase();
    name == "DDJ-1000" || name.starts_with("DDJ-1000 ") && !name.contains("SRT")
}
fn clear_feedback(port: &mut MidiOutputConnection) {
    for channel in 0..4 {
        for key in [
            0x0b, 0x0c, 0x47, 0x1a, 0x58, 0x5a, 0x35, 0x54, 0x10, 0x11, 0x14, 0x4d, 0x5b,
        ] {
            let _ = port.send(&[0x90 + channel, key, 0]);
        }
        let _ = port.send(&[0x90 + channel, 0x5d, 127]);
        for mode in [0, 0x10, 0x20, 0x60] {
            for pad in 0..8 {
                let _ = port.send(&[0x97 + channel * 2, mode + pad, 0]);
            }
        }
        let _ = port.send(&[0xb0 + channel, 2, 0]);
    }
}
impl MidiController {
    pub fn new(sink: impl Fn(MidiEvent) + Send + 'static) -> Self {
        Self::new_matching(sink, supported)
    }
    fn new_matching(
        sink: impl Fn(MidiEvent) + Send + 'static,
        matches: impl Fn(&str) -> bool + Send + 'static,
    ) -> Self {
        let (tx, rx) = mpsc::sync_channel(64);
        let status = Arc::new(Mutex::new(MidiStatus::default()));
        let state = status.clone();
        std::thread::spawn(move || {
            let mut input: Option<MidiInputConnection<()>> = None;
            let mut output: Option<MidiOutputConnection> = None;
            let mut opened_ports = None;
            let (incoming_tx, incoming) = mpsc::sync_channel::<CapturedPacket>(4096);
            let overflow = Arc::new(std::sync::atomic::AtomicBool::new(false));
            let mut lease = Instant::now();
            let mut scan = Instant::now() - Duration::from_secs(2);
            let mut enabled = false;
            let mut generation = 0;
            let mut performance_config:Option<super::performance_transport::Config>=None;
            let mut native:Option<super::performance_transport::Transport>=None;
            let mut next_native_attempt=Instant::now();
            loop {
                process_device_changes();
                let request = match rx.recv_timeout(Duration::from_millis(4)) {
                    Ok(value) => Some(value),
                    Err(mpsc::RecvTimeoutError::Timeout) => None,
                    Err(_) => {
                        if let Some(mut port) = output.take() {
                            clear_feedback(&mut port);
                        }
                        break;
                    }
                };
                if let Some(request) = request {
                    match request {
                        Request::Performance(config)=>{if performance_config.as_ref()!=Some(&config){native=None;performance_config=Some(config);next_native_attempt=Instant::now();}},
                        Request::Lease(value) => {
                            enabled = value;
                            lease = Instant::now();
                        }
                        Request::Send(expected, messages) => {
                            if expected == generation && enabled {
                                if let Some(port) = &mut output {
                                    for message in messages {
                                        if let Err(error) = port.send(&message) {
                                            state.lock().unwrap().error = Some(error.to_string());
                                            enabled = false;
                                            break;
                                        }
                                        state.lock().unwrap().sent += 1;
                                    }
                                }
                            }
                        }
                    }
                }
                if lease.elapsed() > Duration::from_secs(3) {
                    enabled = false;
                }
                let overloaded = overflow.swap(false, std::sync::atomic::Ordering::Relaxed);
                if overloaded {
                    state.lock().unwrap().error =
                        Some("MIDI入力が過密になったため接続をリセットしました".into());
                    input.take();
                    output.take();
                }
                if !enabled {
                    input.take();
                    if let Some(mut port) = output.take() {
                        clear_feedback(&mut port);
                    }
                }
                if enabled && scan.elapsed() >= Duration::from_secs(1) {
                    scan = Instant::now();
                    let result = (|| -> Result<(), String> {
                        let midi_in =
                            MidiInput::new("plumdeck DDJ-1000").map_err(|e| e.to_string())?;
                        let midi_out = MidiOutput::new("plumdeck DDJ-1000 feedback")
                            .map_err(|e| e.to_string())?;
                        let ins: Vec<_> = midi_in
                            .ports()
                            .into_iter()
                            .filter(|p| midi_in.port_name(p).is_ok_and(|n| matches(&n)))
                            .collect();
                        let outs: Vec<_> = midi_out
                            .ports()
                            .into_iter()
                            .filter(|p| midi_out.port_name(p).is_ok_and(|n| matches(&n)))
                            .collect();
                        if ins.len() != 1 || outs.len() != 1 {
                            input.take();
                            output.take();
                            if ins.len() > 1 || outs.len() > 1 {
                                return Err(
                                    "DDJ-1000が複数あります。1台だけ接続してください".into()
                                );
                            }
                            return Err(format!(
                                "DDJ-1000のMIDIポート待ち（入力 {} / 出力 {}）。USB接続を再検出しています",
                                ins.len(), outs.len()
                            ));
                        }
                        let ports = (ins[0].clone(), outs[0].clone());
                        // A quick unplug/replug may occur between scans. Names
                        // remain identical, but endpoint identities change.
                        if input.is_none() || output.is_none() || opened_ports.as_ref() != Some(&ports) {
                            input.take();
                            output.take();
                            generation += 1;
                            {
                                let mut s = state.lock().unwrap();
                                s.received = 0;
                                s.sent = 0;
                            }
                            let send = incoming_tx.clone();
                            let full = overflow.clone();
                            let capture_origin = Instant::now();
                            let mut input_sequence = 0u64;
                            input = Some(
                                midi_in
                                    .connect(
                                        &ins[0],
                                        "DDJ-1000 input",
                                        move |driver_us, bytes, _| {
                                            if bytes.len() > 1024 {full.store(true,std::sync::atomic::Ordering::Relaxed);return;}
                                            input_sequence += 1;
                                            let mut packet=CapturedPacket{generation,captured_us:capture_origin.elapsed().as_micros() as u64,driver_us,sequence:input_sequence,length:bytes.len(),at:Instant::now(),bytes:[0;1024]};
                                            packet.bytes[..bytes.len()].copy_from_slice(bytes);
                                            if send.try_send(packet).is_err(){full.store(true,std::sync::atomic::Ordering::Relaxed);}
                                        },
                                        (),
                                    )
                                    .map_err(|e| e.to_string())?,
                            );
                            output = Some(
                                midi_out
                                    .connect(&outs[0], "DDJ-1000 output")
                                    .map_err(|e| e.to_string())?,
                            );
                            opened_ports = Some(ports);
                        }
                        Ok(())
                    })();
                    state.lock().unwrap().error = result.err();
                }
                let connected = input.is_some() && output.is_some();
                {
                    let mut s = state.lock().unwrap();
                    s.enabled = enabled;
                    s.connected = connected;
                    s.generation = generation;
                    s.device = connected.then(|| "DDJ-1000".into());
                }
                if !connected || !enabled {native=None;}
                else {
                    if let Some(transport)=native.as_mut(){if transport.poll().is_err(){native=None;next_native_attempt=Instant::now()+Duration::from_secs(1);}}
                    if native.is_none()&&Instant::now()>=next_native_attempt {
                        if let Some(config)=&performance_config {native=super::performance_transport::Transport::connect(config).ok();}
                        next_native_attempt=Instant::now()+Duration::from_secs(1);
                    }
                }
                state.lock().unwrap().native_performance=native.as_ref().map(|n|n.observation.clone()).unwrap_or_default();
                let native_performance=native.is_some();
                let mut messages = Vec::new();
                let mut captured_us=Vec::new();let mut driver_timestamps_us=Vec::new();let mut sequences=Vec::new();
                while let Ok(packet) = incoming.try_recv() {
                    if connected && enabled && packet.generation == generation {
                        if let Some(transport)=native.as_mut(){if transport.send(&packet.bytes[..packet.length],packet.at).is_err(){native=None;next_native_attempt=Instant::now()+Duration::from_secs(1);}}
                        messages.push(packet.bytes[..packet.length].to_vec());
                        captured_us.push(packet.captured_us);driver_timestamps_us.push(packet.driver_us);sequences.push(packet.sequence);
                    }
                    if messages.len() >= 128 {
                        break;
                    }
                }
                if !messages.is_empty() {
                    state.lock().unwrap().received += messages.len() as u64;
                    sink(MidiEvent {
                        generation,
                        messages, captured_us, driver_timestamps_us, sequences, native_performance,
                    });
                }
            }
        });
        Self { tx, status, inbox: None }
    }
    pub fn performance(&self,config:super::performance_transport::Config)->Result<(),String>{self.tx.try_send(Request::Performance(config)).map_err(|e|e.to_string())}
    pub fn lease(&self, enabled: bool) -> Result<MidiStatus, String> {
        self.tx
            .try_send(Request::Lease(enabled))
            .map_err(|e| e.to_string())?;
        Ok(self.status.lock().unwrap().clone())
    }
    pub fn send(&self, generation: u64, messages: Vec<Vec<u8>>) -> Result<(), String> {
        if messages.len() > 256
            || messages.iter().any(|m| {
                m.len() != 3 || !matches!(m[0] & 0xf0, 0x90 | 0xb0) || m[1] > 127 || m[2] > 127
            })
        {
            return Err("Invalid DDJ-1000 feedback batch".into());
        }
        self.tx
            .try_send(Request::Send(generation, messages))
            .map_err(|e| e.to_string())
    }
}
#[tauri::command]
pub fn dj_midi_status(
    state: State<'_, MidiController>,
    display: State<'_, super::jog_display::JogDisplay>,
    enabled: bool,
) -> Result<MidiStatus, String> {
    display.lease(enabled);
    let mut status = state.lease(enabled)?;
    status.display = display.status();
    Ok(status)
}
#[tauri::command]
pub fn dj_jog_display_update(
    state: State<'_, MidiController>,
    display: State<'_, super::jog_display::JogDisplay>,
    generation: u64,
    decks: Vec<super::jog_display::DeckDisplay>,
) -> Result<(), String> {
    let status = state.status.lock().unwrap();
    if !status.connected || !status.enabled || status.generation != generation {
        return Err("Stale DDJ-1000 display session".into());
    }
    drop(status);
    display.update(decks)
}
#[tauri::command]
pub fn dj_midi_send(
    state: State<'_, MidiController>,
    generation: u64,
    messages: Vec<Vec<u8>>,
) -> Result<(), String> {
    state.send(generation, messages)
}
#[tauri::command]
pub fn dj_midi_read(state: State<'_, MidiController>) -> Result<Vec<MidiEvent>, String> {
    let result = state.inbox.as_ref().map_or_else(|| Ok(Vec::new()), MidiInbox::read);
    if result.is_err() { let _ = state.lease(false); }
    result
}
pub fn controller(_app: AppHandle) -> MidiController {
    // Never emit from this worker: AppHandle.emit holds the webview manager
    // lock while WKWebView::eval waits for the UI, which may need that lock
    // to service IPC. The UI instead pulls bounded batches via dj_midi_read.
    let (sender, receiver) = mpsc::sync_channel(32);
    let overflow = Arc::new(std::sync::atomic::AtomicBool::new(false));
    let full = overflow.clone();
    let mut controller = MidiController::new(move |event| {
        if sender.try_send(event).is_err() {
            full.store(true, std::sync::atomic::Ordering::SeqCst);
        }
    });
    controller.inbox = Some(MidiInbox { receiver: Mutex::new(receiver), overflow });
    controller
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn midi_inbox_preserves_edges_and_bounds_each_ui_read() {
        let (sender, receiver) = mpsc::sync_channel(32);
        let inbox = MidiInbox {
            receiver: Mutex::new(receiver),
            overflow: Arc::new(std::sync::atomic::AtomicBool::new(false)),
        };
        for i in 0..20 {
            sender.try_send(MidiEvent { native_performance:false, captured_us: vec![], driver_timestamps_us: vec![], sequences: vec![], generation: 7, messages: vec![vec![0x90, 0x36, if i % 2 == 0 {127} else {0}]] }).unwrap();
        }
        let first = inbox.read().unwrap();
        assert_eq!(first.len(), 16);
        for (i, event) in first.iter().enumerate() {
            assert_eq!(event.generation, 7);
            assert_eq!(event.messages[0][2], if i % 2 == 0 {127} else {0});
        }
        assert_eq!(inbox.read().unwrap().len(), 4);
        assert!(inbox.read().unwrap().is_empty());
    }
    #[test]
    fn stalled_ui_does_not_block_producer_and_overflow_invalidates_stream() {
        let (sender, receiver) = mpsc::sync_channel(1);
        let inbox = MidiInbox {
            receiver: Mutex::new(receiver),
            overflow: Arc::new(std::sync::atomic::AtomicBool::new(false)),
        };
        sender.try_send(MidiEvent { native_performance:false, captured_us: vec![], driver_timestamps_us: vec![], sequences: vec![], generation: 1, messages: vec![vec![0x90, 0x36, 127]] }).unwrap();
        assert!(sender.try_send(MidiEvent { native_performance:false, captured_us: vec![], driver_timestamps_us: vec![], sequences: vec![], generation: 1, messages: vec![vec![0x90, 0x36, 0]] }).is_err());
        inbox.overflow.store(true, std::sync::atomic::Ordering::SeqCst);
        assert!(inbox.read().is_err());
        assert!(inbox.read().unwrap().is_empty());
    }
    #[cfg(target_os = "macos")]
    #[test]
    #[ignore = "Requires macOS CoreMIDI and Swift; creates isolated virtual ports"]
    fn coremidi_hotplug_reconnect() {
        let name = format!("plumdeck hotplug test {}", std::process::id());
        let expected = name.clone();
        let controller = MidiController::new_matching(|_| {}, move |n| n == expected);
        controller.lease(true).unwrap();
        let script = r#"
import Foundation
import CoreMIDI
let name = CommandLine.arguments[1] as CFString
var client = MIDIClientRef(), source = MIDIEndpointRef(), destination = MIDIEndpointRef()
MIDIClientCreateWithBlock("plumdeck hotplug fixture" as CFString, &client, nil)
func pause(_ seconds: Double) { RunLoop.current.run(until: Date(timeIntervalSinceNow: seconds)) }
func connect() {
 MIDISourceCreate(client, name, &source)
 MIDIDestinationCreateWithBlock(client, name, &destination) { _, _ in }
}
pause(2); connect(); pause(3)
MIDIEndpointDispose(source); MIDIEndpointDispose(destination)
pause(3); connect(); pause(4)
MIDIClientDispose(client)
"#;
        let mut child = std::process::Command::new("swift")
            .args(["-e", script, &name]).spawn().unwrap();
        let deadline = Instant::now() + Duration::from_secs(20);
        let mut first = None;
        let mut disconnected = false;
        let mut reconnected = false;
        while Instant::now() < deadline {
            let state = controller.lease(true).unwrap();
            if state.connected {
                if let Some(generation) = first {
                    if disconnected && state.generation > generation {
                        reconnected = true;
                        break;
                    }
                } else {
                    first = Some(state.generation);
                }
            } else if first.is_some() {
                disconnected = true;
            }
            std::thread::sleep(Duration::from_millis(100));
        }
        let _ = child.kill();
        let _ = child.wait();
        assert!(reconnected, "first={first:?}, disconnected={disconnected}, status={:?}", controller.status.lock().unwrap());
    }
    #[test]
    #[ignore = "Requires the connected DDJ-1000; sends a cue LED off message"]
    fn real_ddj1000_transport() {
        let controller = MidiController::new(|event| {
            println!("MIDI {}", serde_json::to_string(&event).unwrap());
        });
        let deadline = Instant::now() + Duration::from_secs(10);
        let connected = loop {
            let state = controller.lease(true).unwrap();
            if state.connected {
                break state;
            }
            assert!(
                Instant::now() < deadline,
                "DDJ-1000 unavailable: {:?}",
                state
            );
            std::thread::sleep(Duration::from_millis(100));
        };
        controller
            .send(connected.generation, vec![vec![0x90, 0x0c, 0]])
            .unwrap();
        std::thread::sleep(Duration::from_millis(100));
        let state = controller.lease(true).unwrap();
        assert!(state.sent > 0);
        println!("CONNECTED {}", serde_json::to_string(&state).unwrap());
        // Lease expiry is also the webview-crash failsafe.
        std::thread::sleep(Duration::from_millis(3200));
        let state = controller.status.lock().unwrap().clone();
        assert!(!state.enabled && !state.connected);
    }
    #[test]
    fn exact_model_only() {
        assert!(supported("DDJ-1000"));
        assert!(!supported("DDJ-1000SRT"));
        assert!(!supported("DDJ-1000 SRT"));
        assert!(!supported("DDJ-400"));
    }
    #[test]
    fn feedback_is_bounded_channel_data() {
        let controller = MidiController::new(|_| {});
        assert!(controller.send(0, vec![vec![0x90, 11, 127]]).is_ok());
        assert!(controller.send(0, vec![vec![0xf0, 0, 0]]).is_err());
        assert!(controller.send(0, vec![vec![0x90, 11, 255]]).is_err());
        assert!(controller.send(0, vec![vec![0x90, 11, 0]; 257]).is_err());
    }
}

#[tauri::command]
pub async fn dj_midi_performance_config(controller:State<'_,MidiController>,engine:State<'_,Arc<super::EngineSupervisor>>,session_id:String,sensitivity:f64,ranges:[f64;4],cues:[f64;4])->Result<(),String>{
    let engine=engine.inner().clone();
    let reply=tauri::async_runtime::spawn_blocking(move||engine.send(&session_id,"performance.endpoint",serde_json::json!({}))).await.map_err(|e|e.to_string())??;
    let value=reply.data.ok_or("Native input unavailable")?;
    let config=super::performance_transport::Config{path:value["path"].as_str().ok_or("No input endpoint")?.into(),token:value["token"].as_str().ok_or("No input token")?.into(),sensitivity,ranges,cues};
    controller.performance(config)
}
