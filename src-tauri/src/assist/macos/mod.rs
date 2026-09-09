//! macOS implementation of assist-mode deck observation.

pub mod ax;
pub mod decks;
pub mod open_files;

use std::sync::{Mutex, TryLockError};
use std::time::{SystemTime, UNIX_EPOCH};

use crate::assist::AssistSnapshot;
use ax::AxRef;
use decks::Node;
use open_files::OpenFilesCache;

/// Upper bound on the nodes we read from one window.
///
/// The rekordbox deck window is ~250 nodes. The cap exists so an unexpected
/// view (a huge browser list, a modal) degrades into a partial read instead of
/// a multi-second stall on the polling thread.
const MAX_NODES: usize = 1500;
const MAX_DEPTH: usize = 24;
const MAX_CHILDREN: usize = 400;
const MAX_WINDOWS: usize = 16;

struct CachedApplication {
    pid: i32,
    path: String,
    element: AxRef,
}

#[derive(Default)]
struct Inner {
    application: Option<CachedApplication>,
    open_files: Option<OpenFilesCache>,
}

/// Serializes assist reads so overlapping polls can never run two accessibility
/// walks at once, and keeps the application element cached between polls.
#[derive(Default)]
pub struct AssistState {
    inner: Mutex<Inner>,
    last: Mutex<Option<AssistSnapshot>>,
}

impl AssistState {
    pub fn snapshot(&self) -> AssistSnapshot {
        let mut inner = match self.inner.try_lock() {
            Err(TryLockError::WouldBlock) => {
                return self
                    .last
                    .lock()
                    .unwrap_or_else(|p| p.into_inner())
                    .clone()
                    .unwrap_or_else(|| AssistSnapshot {
                        supported: true,
                        unavailable_reason: Some("読み取り中です".into()),
                        ..Default::default()
                    })
            }
            Ok(guard) => guard,
            // A panic in a previous read must not disable assist mode forever.
            Err(TryLockError::Poisoned(poisoned)) => poisoned.into_inner(),
        };

        let permission_granted = ax::is_process_trusted();
        let Some((pid, path)) = resolve_application(&mut inner) else {
            inner.application = None;
            return AssistSnapshot {
                supported: true,
                permission_granted,
                app_running: false,
                unavailable_reason: Some("rekordbox が起動していません".into()),
                captured_at_ms: now_ms(),
                ..Default::default()
            };
        };

        if !permission_granted {
            return AssistSnapshot {
                supported: true,
                permission_granted,
                app_running: true,
                app_path: Some(path),
                unavailable_reason: Some(
                    "アクセシビリティ権限がないためデッキを読み取れません".into(),
                ),
                captured_at_ms: now_ms(),
                ..Default::default()
            };
        }

        let element = inner
            .application
            .as_ref()
            .map(|application| application.element.as_raw());
        let Some(element) = element else {
            return AssistSnapshot {
                supported: true,
                permission_granted,
                app_running: true,
                app_path: Some(path),
                unavailable_reason: Some("rekordbox のUI情報を取得できませんでした".into()),
                captured_at_ms: now_ms(),
                ..Default::default()
            };
        };

        ax::begin_read();
        let Some((window, window_right)) = main_window(element) else {
            return AssistSnapshot {
                supported: true,
                permission_granted,
                app_running: true,
                app_path: Some(path),
                unavailable_reason: Some(
                    "rekordbox のウィンドウが見つかりません（最小化中の可能性があります）".into(),
                ),
                captured_at_ms: now_ms(),
                ..Default::default()
            };
        };

        let mut nodes = Vec::new();
        let truncated = !collect_nodes(window.as_raw(), 0, &mut nodes, &mut 0);
        let captured_at_ms = now_ms();
        let (mut decks, mut warnings) = decks::parse_decks(&nodes, window_right);
        if truncated {
            decks.clear();
        }
        if truncated {
            warnings.push("UI読み取りの時間または要素数の上限に達しました".into());
        }
        let signature = decks::signature(&decks);

        let (open_audio_paths, open_paths_error) = refresh_open_files(&mut inner, pid, &signature);

        let unavailable_reason = if decks.is_empty() {
            Some("rekordbox の画面からデッキを特定できませんでした（PERFORMANCE 画面を表示してください）".into())
        } else {
            None
        };

        let snapshot = AssistSnapshot {
            supported: true,
            permission_granted,
            app_running: true,
            app_path: Some(path),
            layout_hint: decks::layout_hint(&nodes),
            decks,
            open_audio_paths,
            open_paths_error,
            signature,
            captured_at_ms,
            unavailable_reason,
            warnings,
        };
        *self.last.lock().unwrap_or_else(|p| p.into_inner()) = Some(snapshot.clone());
        snapshot
    }

    /// User-initiated only: shows the macOS accessibility permission prompt.
    pub fn request_permission(&self) -> bool {
        ax::prompt_for_trust()
    }

    pub fn open_permission_settings(&self) -> Result<(), String> {
        std::process::Command::new("/usr/bin/open")
            .arg("x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility")
            .status()
            .map_err(|error| format!("設定を開けませんでした: {error}"))
            .and_then(|status| {
                if status.success() {
                    Ok(())
                } else {
                    Err("設定を開けませんでした".into())
                }
            })
    }
}

/// Returns the live rekordbox pid, reusing the cached accessibility element when
/// the process is still the same one.
fn resolve_application(inner: &mut Inner) -> Option<(i32, String)> {
    if let Some(application) = &inner.application {
        // A pid can be recycled, so confirm the executable still matches before
        // trusting a cached element.
        if ax::executable_path(application.pid).as_deref() == Some(application.path.as_str()) {
            return Some((application.pid, application.path.clone()));
        }
    }
    let (pid, path) = ax::find_rekordbox_process()?;
    inner.application = ax::application_element(pid).map(|element| CachedApplication {
        pid,
        path: path.clone(),
        element,
    });
    Some((pid, path))
}

/// The largest window of the application.
///
/// Starting from a window rather than the application element is what keeps the
/// menu bar — roughly 800 further nodes — out of every walk.
fn main_window(application: ax::AXUIElementRef) -> Option<(AxRef, f64)> {
    let windows = ax::attribute_elements(application, "AXWindows", MAX_WINDOWS);
    windows
        .into_iter()
        .filter_map(|window| {
            let (width, height) = ax::attribute_size(window.as_raw(), "AXSize")?;
            let (x, _) = ax::attribute_position(window.as_raw(), "AXPosition")?;
            Some((window, width, height, x))
        })
        .max_by(|a, b| {
            (a.1 * a.2)
                .partial_cmp(&(b.1 * b.2))
                .unwrap_or(std::cmp::Ordering::Equal)
        })
        .map(|(window, width, _, x)| (window, x + width))
}

/// Depth-first walk of one window subtree. Returns false when the budget ran out.
fn collect_nodes(
    element: ax::AXUIElementRef,
    depth: usize,
    nodes: &mut Vec<Node>,
    visited: &mut usize,
) -> bool {
    if *visited >= MAX_NODES || ax::budget_expired() {
        return false;
    }
    *visited += 1;
    let role = ax::attribute_string(element, "AXRole").unwrap_or_default();
    let (x, y) = ax::attribute_position(element, "AXPosition").unwrap_or((f64::NAN, f64::NAN));
    let (width, height) = ax::attribute_size(element, "AXSize").unwrap_or((0.0, 0.0));
    if x.is_finite() && y.is_finite() {
        nodes.push(Node {
            // Only text-bearing roles are asked for a value; buttons and groups
            // would cost an extra accessibility round trip each for nothing.
            value: if matches!(
                role.as_str(),
                decks::ROLE_STATIC_TEXT | decks::ROLE_TEXT_AREA | decks::ROLE_POPUP_BUTTON
            ) {
                ax::attribute_string(element, "AXValue").unwrap_or_default()
            } else {
                String::new()
            },
            role,
            x,
            y,
            width,
            height,
        });
    }
    if depth >= MAX_DEPTH {
        return true;
    }
    for child in ax::attribute_elements(element, "AXChildren", MAX_CHILDREN) {
        if !collect_nodes(child.as_raw(), depth + 1, nodes, visited) {
            return false;
        }
    }
    !ax::budget_expired()
}

/// Re-lists rekordbox's open audio files only when the decks changed or the
/// cached listing aged out; `lsof` is far too costly to run on every poll.
fn refresh_open_files(
    inner: &mut Inner,
    pid: i32,
    signature: &str,
) -> (Vec<String>, Option<String>) {
    if let Some(cache) = &inner.open_files {
        if cache.is_usable(pid, signature) {
            return (cache.paths.clone(), cache.error.clone());
        }
    }
    let refreshes = inner
        .open_files
        .as_ref()
        .filter(|c| c.pid == pid && c.signature == signature)
        .map_or(1, |c| c.refreshes.saturating_add(1));
    match open_files::read_open_audio_paths(pid) {
        Ok(paths) => {
            inner.open_files = Some(OpenFilesCache {
                paths: paths.clone(),
                signature: signature.to_string(),
                pid,
                captured_at: std::time::Instant::now(),
                refreshes,
                error: None,
            });
            (paths, None)
        }
        Err(error) => {
            // Keep serving the previous listing rather than claiming the decks
            // suddenly hold nothing.
            let stale = inner
                .open_files
                .as_ref()
                .filter(|cache| cache.pid == pid)
                .map(|cache| cache.paths.clone())
                .unwrap_or_default();
            inner.open_files = Some(OpenFilesCache {
                paths: stale.clone(),
                signature: signature.into(),
                pid,
                captured_at: std::time::Instant::now(),
                refreshes,
                error: Some(error.clone()),
            });
            (stale, Some(error))
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn visited_cap_stops_before_any_ax_call() {
        let mut visited = MAX_NODES;
        assert!(!collect_nodes(
            std::ptr::null(),
            0,
            &mut Vec::new(),
            &mut visited
        ));
    }

    #[test]
    fn overlapping_read_returns_original_timestamp() {
        let state = AssistState::default();
        *state.last.lock().unwrap() = Some(AssistSnapshot {
            captured_at_ms: 42,
            ..Default::default()
        });
        let _guard = state.inner.lock().unwrap();
        assert_eq!(state.snapshot().captured_at_ms, 42);
    }

    /// Reads the decks out of the rekordbox that is actually running.
    ///
    /// Ignored by default because it needs rekordbox open with tracks loaded and
    /// accessibility permission granted to the test runner's terminal. Run with
    /// `cargo test --lib assist -- --ignored --nocapture` to re-verify the
    /// parser against a new rekordbox build.
    #[test]
    #[ignore = "needs a running, accessibility-trusted rekordbox"]
    fn reads_the_running_rekordbox() {
        let state = AssistState::default();
        let started = std::time::Instant::now();
        let snapshot = state.snapshot();
        println!("first read took {:?}", started.elapsed());
        println!("{snapshot:#?}");
        let cached = std::time::Instant::now();
        let second = state.snapshot();
        println!("cached read took {:?}", cached.elapsed());
        assert!(second.supported);
    }
}

fn now_ms() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|duration| duration.as_millis() as u64)
        .unwrap_or(0)
}
