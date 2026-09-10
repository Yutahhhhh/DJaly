//! Bounded local channel independent of WebView rendering and notification ACKs.
#[cfg(unix)]
use std::os::unix::net::UnixStream as LocalStream;
#[cfg(windows)]
use windows_pipe::LocalStream;

#[cfg(windows)]
mod windows_pipe {
    use std::{cell::Cell, fs::{File, OpenOptions}, io::{self, Read, Write},
        os::windows::io::AsRawHandle, time::{Duration, Instant}};
    #[link(name = "kernel32")]
    extern "system" {
        fn ReadFile(handle: *mut std::ffi::c_void, buffer: *mut u8, length: u32,
            read: *mut u32, overlapped: *mut std::ffi::c_void) -> i32;
        fn SetNamedPipeHandleState(handle: *mut std::ffi::c_void, mode: *const u32,
            count: *const u32, timeout: *const u32) -> i32;
    }
    pub struct LocalStream {
        file: File,
        timeout: Cell<Option<Duration>>,
        nonblocking: Cell<bool>,
    }
    impl LocalStream {
        pub fn connect(path: &str) -> io::Result<Self> {
            // Only this machine's named pipes; never open an arbitrary file or UNC share.
            if !path.starts_with(r"\\.\pipe\") {
                return Err(io::Error::new(io::ErrorKind::InvalidInput, "Expected local named pipe"));
            }
            let file = OpenOptions::new().read(true).write(true).open(path)?;
            let mode = 1u32; // PIPE_NOWAIT | PIPE_READMODE_BYTE
            if unsafe { SetNamedPipeHandleState(file.as_raw_handle(), &mode,
                std::ptr::null(), std::ptr::null()) } == 0 {
                return Err(io::Error::last_os_error());
            }
            Ok(Self { file, timeout: Cell::new(None), nonblocking: Cell::new(false) })
        }
        pub fn set_read_timeout(&self, timeout: Option<Duration>) -> io::Result<()> {
            self.timeout.set(timeout); Ok(())
        }
        pub fn set_write_timeout(&self, _timeout: Option<Duration>) -> io::Result<()> {
            // PIPE_NOWAIT bounds every write, including the handshake.
            Ok(())
        }
        pub fn set_nonblocking(&self, value: bool) -> io::Result<()> {
            self.nonblocking.set(value); Ok(())
        }
    }
    impl Read for LocalStream {
        fn read(&mut self, bytes: &mut [u8]) -> io::Result<usize> {
            let start = Instant::now();
            loop {
                let mut count = 0u32;
                // std::fs::File maps ERROR_NO_DATA to EOF, losing the distinction
                // between an empty nonblocking pipe and a disconnected peer.
                let result = if unsafe { ReadFile(self.file.as_raw_handle(), bytes.as_mut_ptr(),
                    bytes.len().min(u32::MAX as usize) as u32, &mut count, std::ptr::null_mut()) } != 0 {
                    Ok(count as usize)
                } else { Err(io::Error::last_os_error()) };
                match result {
                    Err(e) if e.raw_os_error() == Some(232) => {
                        if self.nonblocking.get() {
                            return Err(io::ErrorKind::WouldBlock.into());
                        }
                        if self.timeout.get().is_some_and(|t| start.elapsed() >= t) {
                            return Err(io::ErrorKind::TimedOut.into());
                        }
                        std::thread::sleep(Duration::from_millis(1));
                    }
                    result => return result,
                }
            }
        }
    }
    impl Write for LocalStream {
        fn write(&mut self, bytes: &[u8]) -> io::Result<usize> { self.file.write(bytes) }
        fn flush(&mut self) -> io::Result<()> { Ok(()) }
    }
}

use serde::{Deserialize, Serialize};

use serde_json::{json, Value};
use std::{
    io::{Read, Write},
    time::{Duration, Instant},
};

#[derive(Clone, Debug, Deserialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct Config {
    pub path: String,
    pub token: String,
    pub sensitivity: f64,
    pub ranges: [f64; 4],
    pub cues: [f64; 4],
}

#[derive(Clone, Debug, Default, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct Observation {
    pub active: bool,
    pub cues: [f64; 4],
    pub ranges: [f64; 4],
}

pub struct Transport {
    stream: LocalStream,
    input: Vec<u8>,
    generations: [u32; 4],
    generation_since: [Instant; 4],
    origin: Instant,
    offset: f64,
    seq: u64,
    last_write: Instant,
    pub observation: Observation,
}

impl Transport {
    pub fn connect(config: &Config) -> Result<Self, String> {
        if !config.sensitivity.is_finite()
            || config.sensitivity <= 0.0
            || config.sensitivity > 20.0
            || config
                .ranges
                .iter()
                .chain(config.cues.iter())
                .any(|v| !v.is_finite())
        {
            return Err("Invalid performance settings".into());
        }
        let mut stream = LocalStream::connect(&config.path).map_err(|e| e.to_string())?;
        stream
            .set_read_timeout(Some(Duration::from_millis(200)))
            .map_err(|e| e.to_string())?;
        stream
            .set_write_timeout(Some(Duration::from_millis(20)))
            .map_err(|e| e.to_string())?;
        let origin = Instant::now();
        let mut hello = serde_json::to_vec(&json!({
            "token": config.token,
            "sensitivity": config.sensitivity,
            "ranges": config.ranges,
            "cues": config.cues
        }))
        .unwrap();
        hello.push(b'\n');
        stream.write_all(&hello).map_err(|e| e.to_string())?;
        let mut input = Vec::new();
        let mut byte = [0];
        while input.len() < 16384 {
            stream.read_exact(&mut byte).map_err(|e| e.to_string())?;
            if byte[0] == b'\n' {
                break;
            }
            input.push(byte[0]);
        }
        let state: Value = serde_json::from_slice(&input).map_err(|e| e.to_string())?;
        let offset = state["nativeUs"]
            .as_f64()
            .ok_or("Missing native clock")?
            - origin.elapsed().as_secs_f64() * 500000.0;
        stream.set_nonblocking(true).map_err(|e| e.to_string())?;
        let mut transport = Self {
            stream,
            input: Vec::new(),
            generations: [0; 4],
            generation_since: [origin; 4],
            origin,
            offset,
            seq: 0,
            last_write: Instant::now(),
            observation: Observation {
                active: true,
                cues: config.cues,
                ranges: config.ranges,
            },
        };
        transport.observe(&state);
        Ok(transport)
    }

    fn observe(&mut self, value: &Value) {
        for i in 0..4 {
            if let Some(g) = value["decks"][i]["generation"].as_u64() {
                if self.generations[i] != g as u32 {
                    self.generations[i] = g as u32;
                    self.generation_since[i] = Instant::now();
                }
            }
            if let Some(c) = value["decks"][i]["cueMs"].as_f64() {
                self.observation.cues[i] = c;
            }
            if let Some(r) = value["decks"][i]["range"].as_f64() {
                self.observation.ranges[i] = r;
            }
        }
    }

    pub fn poll(&mut self) -> Result<(), String> {
        let mut bytes = [0; 4096];
        loop {
            match self.stream.read(&mut bytes) {
                Ok(0) => return Err("Native input disconnected".into()),
                Ok(n) => {
                    self.input.extend_from_slice(&bytes[..n]);
                    if self.input.len() > 16384 {
                        return Err("Native observation overflow".into());
                    }
                }
                Err(e) if e.kind() == std::io::ErrorKind::WouldBlock => break,
                Err(e) => return Err(e.to_string()),
            }
        }
        while let Some(end) = self.input.iter().position(|&b| b == b'\n') {
            let value: Value =
                serde_json::from_slice(&self.input[..end]).map_err(|e| e.to_string())?;
            self.observe(&value);
            self.input.drain(..=end);
        }
        if self.last_write.elapsed() > Duration::from_millis(200) {
            self.send(&[], Instant::now())?;
        }
        Ok(())
    }

    pub fn send(&mut self, bytes: &[u8], captured: Instant) -> Result<(), String> {
        // Long SysEx belongs to the display path. Channel messages and running
        // status are streamed in at most three-byte fragments without allocation.
        if bytes.first() == Some(&0xf0) {
            return Ok(());
        }
        let fragments = if bytes.is_empty() {
            1
        } else {
            bytes.len().div_ceil(3)
        };
        if fragments > 64 {
            return Err("Native input batch too large".into());
        }
        let mut buffer = [0u8; 48 * 64];
        for fragment in 0..fragments {
            self.seq += 1;
            let row = &mut buffer[fragment * 48..(fragment + 1) * 48];
            row[..8].copy_from_slice(&self.seq.to_le_bytes());
            let elapsed = if captured >= self.origin {
                captured.duration_since(self.origin).as_secs_f64()
            } else {
                -self.origin.duration_since(captured).as_secs_f64()
            };
            let native = (self.offset + elapsed * 1e6).max(0.0) as u64;
            row[8..16].copy_from_slice(&native.to_le_bytes());
            for i in 0..4 {
                // A packet queued before a load observation belongs to the earlier track.
                // Never relabel it with the newly observed generation when draining MIDI.
                let generation = if captured >= self.generation_since[i] {
                    self.generations[i]
                } else {
                    0
                };
                row[16 + i * 4..20 + i * 4].copy_from_slice(&generation.to_le_bytes());
            }
            let first = fragment * 3;
            let n = bytes.len().saturating_sub(first).min(3);
            row[32] = n as u8;
            if n > 0 {
                row[33..33 + n].copy_from_slice(&bytes[first..first + n]);
            }
        }
        // Nonblocking writes never wait behind the WebView. Any partial write
        // invalidates the connection; its drop aborts native gestures.
        match self.stream.write(&buffer[..fragments * 48]) {
            Ok(n) if n == fragments * 48 => {
                self.last_write = Instant::now();
                Ok(())
            }
            Ok(_) => Err("Native input overflow".into()),
            Err(e) => Err(e.to_string()),
        }
    }
}

#[cfg(all(test, unix))]
mod tests {
    use super::*;

    #[test]
    fn queued_midi_is_not_relabelled_after_track_replacement() {
        let (stream, mut peer) = LocalStream::pair().unwrap();
        let origin = Instant::now() - Duration::from_secs(1);
        let mut transport = Transport {
            stream,
            input: Vec::new(),
            generations: [1; 4],
            generation_since: [origin; 4],
            origin,
            offset: 1e6,
            seq: 0,
            last_write: origin,
            observation: Observation::default(),
        };
        let captured = Instant::now() - Duration::from_millis(1);
        transport.observe(&json!({"decks":[{"generation":2},{"generation":1},{"generation":1},{"generation":1}]}));
        transport.send(&[0x90, 0x36, 127], captured).unwrap();
        let mut record = [0u8; 48];
        peer.read_exact(&mut record).unwrap();
        assert_eq!(
            u32::from_le_bytes(record[16..20].try_into().unwrap()),
            0
        );
        assert_eq!(
            u32::from_le_bytes(record[20..24].try_into().unwrap()),
            1
        );
        transport.send(&[0x90, 0x36, 0], Instant::now()).unwrap();
        peer.read_exact(&mut record).unwrap();
        assert_eq!(
            u32::from_le_bytes(record[16..20].try_into().unwrap()),
            2
        );
        assert_eq!(u64::from_le_bytes(record[..8].try_into().unwrap()), 2);
    }
}

#[cfg(all(test, windows))]
mod windows_tests {
    use super::*;
    use std::{fs::File, os::windows::io::{FromRawHandle, AsRawHandle}};
    #[link(name="kernel32")]
    extern "system" {
        fn CreateNamedPipeW(name:*const u16, access:u32, mode:u32, instances:u32,
            output:u32, input:u32, timeout:u32, security:*const std::ffi::c_void) -> *mut std::ffi::c_void;
        fn ConnectNamedPipe(handle:*mut std::ffi::c_void, overlapped:*mut std::ffi::c_void) -> i32;
    }
    #[test]
    fn windows_pipe_handshake_and_timestamped_midi() {
        let path=format!(r"\\.\pipe\plumdeck-test-{}-{}",std::process::id(),
            std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).unwrap().as_nanos());
        let name=path.encode_utf16().chain(Some(0)).collect::<Vec<_>>();
        let handle=unsafe { CreateNamedPipeW(name.as_ptr(),3,0,1,65536,65536,0,std::ptr::null()) };
        assert_ne!(handle as isize,-1);
        let mut file=unsafe { File::from_raw_handle(handle) };
        let server=std::thread::spawn(move || {
            let result=unsafe { ConnectNamedPipe(file.as_raw_handle(),std::ptr::null_mut()) };
            if result==0 { assert_eq!(std::io::Error::last_os_error().raw_os_error(),Some(535)); }
            let mut hello=Vec::new(); let mut byte=[0];
            loop { file.read_exact(&mut byte).unwrap(); if byte[0]==b'\n' {break} hello.push(byte[0]); }
            assert_eq!(serde_json::from_slice::<Value>(&hello).unwrap()["token"],"test-token");
            file.write_all(b"{\"nativeUs\":1000,\"decks\":[{\"generation\":1}]}\n").unwrap();
            let mut packet=[0u8;48]; file.read_exact(&mut packet).unwrap();
            assert_eq!(&packet[33..36],&[0x90,0x36,127]);
            assert_eq!(u32::from_le_bytes(packet[16..20].try_into().unwrap()),1);
        });
        let mut transport=Transport::connect(&Config { path,token:"test-token".into(),
            sensitivity:0.1,ranges:[16.0;4],cues:[0.0;4] }).unwrap();
        transport.poll().unwrap(); // Empty pipe must return immediately.
        transport.send(&[0x90,0x36,127],Instant::now()).unwrap();
        server.join().unwrap();
    }
}
