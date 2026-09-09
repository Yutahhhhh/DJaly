//! Tauri commands for assist mode.
//!
//! Assist mode is a passive observer: it never starts the DJ engine, never opens
//! a MIDI port and never claims an audio device, so rekordbox keeps exclusive
//! ownership of the hardware while it is active.

use std::sync::Mutex;

use serde::Serialize;
use tauri::{LogicalSize, Manager, PhysicalPosition, PhysicalSize, Runtime, State, Window};

use super::{AssistSnapshot, AssistState};

/// The window geometry assist mode has to put back when the DJ leaves it.
#[derive(Default)]
pub struct WindowBounds {
    saved: Mutex<Option<SavedBounds>>,
}

#[derive(Clone, Copy)]
struct SavedBounds {
    position: PhysicalPosition<i32>,
    size: PhysicalSize<u32>,
}

#[derive(Serialize)]
pub struct CompactWindowResult {
    /// False when the window could not be resized; the UI stays usable anyway.
    pub applied: bool,
    pub message: Option<String>,
}

#[tauri::command]
pub async fn assist_snapshot(app: tauri::AppHandle) -> Result<AssistSnapshot, String> {
    tauri::async_runtime::spawn_blocking(move || app.state::<AssistState>().snapshot())
        .await
        .map_err(|error| format!("読み取りに失敗しました: {error}"))
}

/// Shows the macOS accessibility prompt. Only ever called from a user click.
#[tauri::command(async)]
pub fn assist_request_accessibility(state: State<'_, AssistState>) -> bool {
    state.request_permission()
}

#[tauri::command(async)]
pub fn assist_open_accessibility_settings(state: State<'_, AssistState>) -> Result<(), String> {
    state.open_permission_settings()
}

/// Shrinks the main window so it can sit beside rekordbox, remembering the
/// bounds it had so leaving assist mode restores them exactly.
#[tauri::command(async)]
pub fn assist_enter_compact_window<R: Runtime>(
    window: Window<R>,
    bounds: State<'_, WindowBounds>,
    width: f64,
    height: f64,
) -> CompactWindowResult {
    if window.is_fullscreen().unwrap_or(false) || window.is_maximized().unwrap_or(false) {
        return CompactWindowResult {
            applied: false,
            message: Some("コンパクト表示にはウィンドウ表示へ戻してください".into()),
        };
    }
    let mut saved = lock(&bounds.saved);
    if saved.is_none() {
        match (window.outer_position(), window.inner_size()) {
            (Ok(position), Ok(size)) => *saved = Some(SavedBounds { position, size }),
            _ => {
                return CompactWindowResult {
                    applied: false,
                    message: Some(
                        "現在のウィンドウ位置を取得できなかったため、サイズは変更しませんでした"
                            .into(),
                    ),
                }
            }
        }
    }
    // Leave the minimum size unrestricted first: an existing minimum larger than
    // the compact size would silently clamp the resize.
    let _ = window.set_min_size(None::<LogicalSize<f64>>);
    match window.set_size(LogicalSize::new(width, height)) {
        Ok(()) => CompactWindowResult {
            applied: true,
            message: None,
        },
        Err(error) => CompactWindowResult {
            applied: false,
            message: Some(format!("ウィンドウを縮小できませんでした: {error}")),
        },
    }
}

/// Puts back the bounds saved by [`assist_enter_compact_window`].
#[tauri::command(async)]
pub fn assist_exit_compact_window<R: Runtime>(
    window: Window<R>,
    bounds: State<'_, WindowBounds>,
) -> CompactWindowResult {
    let restored = lock(&bounds.saved).take();
    let Some(restored) = restored else {
        return CompactWindowResult {
            applied: false,
            message: None,
        };
    };
    let size = window.set_size(restored.size);
    let position = window.set_position(restored.position);
    match size.and(position) {
        Ok(()) => CompactWindowResult {
            applied: true,
            message: None,
        },
        Err(error) => CompactWindowResult {
            applied: false,
            message: Some(format!("元のウィンドウサイズに戻せませんでした: {error}")),
        },
    }
}

#[tauri::command(async)]
pub fn assist_set_always_on_top<R: Runtime>(
    window: Window<R>,
    enabled: bool,
) -> Result<(), String> {
    window
        .set_always_on_top(enabled)
        .map_err(|error| format!("常に最前面の切り替えに失敗しました: {error}"))
}

fn lock<T>(mutex: &Mutex<T>) -> std::sync::MutexGuard<'_, T> {
    match mutex.lock() {
        Ok(guard) => guard,
        Err(poisoned) => poisoned.into_inner(),
    }
}
