//! The audio files the rekordbox process currently has open.
//!
//! This is only a candidate set. rekordbox keeps the sampler banks and the
//! metronome click open at all times, and the order it reports them in has
//! nothing to do with deck order — so these paths mean "one of these may be on a
//! deck", never "this file is on deck N". Deciding which is which is the
//! backend's job, using the deck title/artist plus the rekordbox library.

use std::collections::BTreeSet;
use std::io::Read;
use std::process::{Command, Stdio};
use std::time::{Duration, Instant};

const AUDIO_EXTENSIONS: [&str; 13] = [
    "mp3", "m4a", "aac", "wav", "wave", "aif", "aiff", "aifc", "flac", "ogg", "oga", "alac", "mp4",
];

/// How long a set of open paths stays usable before we look again, even if the
/// decks have not visibly changed.
pub const CACHE_TTL: Duration = Duration::from_secs(20);

pub struct OpenFilesCache {
    pub paths: Vec<String>,
    pub signature: String,
    pub pid: i32,
    pub captured_at: Instant,
    pub refreshes: u32,
    pub error: Option<String>,
}

impl OpenFilesCache {
    pub fn is_usable(&self, pid: i32, signature: &str) -> bool {
        self.pid == pid
            && (self.captured_at.elapsed() < Duration::from_secs(1)
                || (self.signature == signature
                    && self.captured_at.elapsed()
                        < if self.refreshes < 4 {
                            Duration::from_secs(2)
                        } else {
                            CACHE_TTL
                        }))
    }
}

fn has_audio_extension(path: &str) -> bool {
    let Some(extension) = path
        .rsplit_once('.')
        .map(|(_, ext)| ext.to_ascii_lowercase())
    else {
        return false;
    };
    AUDIO_EXTENSIONS.contains(&extension.as_str())
}

/// Extracts the `n`-prefixed name records from `lsof -F` output.
pub fn parse_lsof_names(output: &str) -> Vec<String> {
    let mut paths = BTreeSet::new();
    for line in output.lines() {
        let Some(path) = line.strip_prefix('n') else {
            continue;
        };
        // lsof appends state markers such as " (deleted)" to some names.
        let path = path.trim_end();
        if path.starts_with('/') && has_audio_extension(path) {
            paths.insert(path.to_string());
        }
    }
    paths.into_iter().collect()
}

/// Lists the open audio files of one process. Read-only and bounded.
pub fn read_open_audio_paths(pid: i32) -> Result<Vec<String>, String> {
    let mut child = Command::new("/usr/sbin/lsof")
        .args(["-w", "-S", "2", "-Fn", "-p", &pid.to_string()])
        .stdout(Stdio::piped())
        .stderr(Stdio::null())
        .spawn()
        .map_err(|error| format!("lsof を実行できませんでした: {error}"))?;
    let stdout = child
        .stdout
        .take()
        .ok_or("lsof の出力を取得できませんでした")?;
    let (send, receive) = std::sync::mpsc::sync_channel(1);
    const OUTPUT_CAP: u64 = 4 * 1024 * 1024;
    std::thread::spawn(move || {
        let mut bytes = Vec::new();
        let result = stdout
            .take(OUTPUT_CAP + 1)
            .read_to_end(&mut bytes)
            .map(|_| bytes);
        let _ = send.send(result);
    });
    let deadline = Instant::now() + Duration::from_secs(3);
    let result: Result<(Vec<u8>, std::process::ExitStatus), String> = (|| {
        let stdout = receive
            .recv_timeout(deadline.saturating_duration_since(Instant::now()))
            .map_err(|_| "lsof の読み取りがタイムアウトしました".to_string())?
            .map_err(|error| format!("lsof の読み取りに失敗しました: {error}"))?;
        if stdout.len() as u64 > OUTPUT_CAP {
            return Err("lsof の出力が上限を超えました".into());
        }
        loop {
            if let Some(status) = child.try_wait().map_err(|e| e.to_string())? {
                return Ok((stdout, status));
            }
            if Instant::now() >= deadline {
                return Err("lsof がタイムアウトしました".into());
            }
            std::thread::sleep(Duration::from_millis(10));
        }
    })();
    if result.is_err() {
        let _ = child.kill();
        // Reap off the polling thread: even wait can stall on an unresponsive mount.
        std::thread::spawn(move || {
            let _ = child.wait();
        });
    }
    let (stdout, status) = result?;
    // lsof exits non-zero when some descriptors could not be inspected; the
    // records it did produce are still valid, so only a total absence is fatal.
    let text = String::from_utf8_lossy(&stdout);
    let paths = parse_lsof_names(&text);
    if paths.is_empty() && !status.success() {
        let stderr = "lsof が終了しました";
        return Err(format!(
            "rekordbox が開いているファイルを取得できませんでした: {}",
            stderr.lines().next().unwrap_or("原因不明").trim()
        ));
    }
    Ok(paths)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn cache_throttles_flapping_and_retries_early_listing() {
        let mut cache = OpenFilesCache {
            paths: vec![],
            signature: "first".into(),
            pid: 1,
            captured_at: Instant::now(),
            refreshes: 1,
            error: None,
        };
        assert!(cache.is_usable(1, "changed"));
        assert!(!cache.is_usable(2, "first"));
        cache.captured_at = Instant::now() - Duration::from_secs(3);
        assert!(!cache.is_usable(1, "first"));
        cache.refreshes = 4;
        assert!(cache.is_usable(1, "first"));
        assert!(!cache.is_usable(1, "changed"));
    }

    #[test]
    fn keeps_only_audio_paths_and_drops_duplicates() {
        let output = "p73852\n\
                      fcwd\nn/Users/dj\n\
                      f11\nn/Applications/rekordbox 7/rekordbox.app/Contents/Resources/binary/Click Sound 01 Electronic.wav\n\
                      f12\nn/Users/dj/Music/PioneerDJ/Sampler/OSC_SAMPLER/PRESET ONESHOT/HORN.wav\n\
                      f13\nn/Users/dj/audios/Usher/Bad Girl.mp3\n\
                      f14\nn/Users/dj/audios/Usher/Bad Girl.mp3\n\
                      f15\nn/Users/dj/Library/Pioneer/rekordbox/master.db\n\
                      f16\nn->0x1234\n";
        let paths = parse_lsof_names(output);
        assert_eq!(
            paths,
            vec![
                "/Applications/rekordbox 7/rekordbox.app/Contents/Resources/binary/Click Sound 01 Electronic.wav".to_string(),
                "/Users/dj/Music/PioneerDJ/Sampler/OSC_SAMPLER/PRESET ONESHOT/HORN.wav".to_string(),
                "/Users/dj/audios/Usher/Bad Girl.mp3".to_string(),
            ]
        );
    }

    #[test]
    fn sampler_and_click_files_are_not_filtered_out_here() {
        // Filtering them by name would be guesswork; identity is resolved later
        // against the library, so this layer must not drop plausible tracks.
        let paths = parse_lsof_names("n/Users/dj/audios/sampler/intro voice.wav\n");
        assert_eq!(paths.len(), 1);
    }

    #[test]
    fn non_audio_and_relative_names_are_ignored() {
        let paths = parse_lsof_names("n/Users/dj/Library/x.db\nnrekordbox.mp3\nn/tmp/a.MP3\n");
        assert_eq!(paths, vec!["/tmp/a.MP3".to_string()]);
    }
}
