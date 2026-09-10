mod waveform;
mod junction_exchange_files;
use std::env;
use std::sync::Arc;
use tauri::menu::{Menu, MenuItem, PredefinedMenuItem, Submenu};
use tauri::{Manager, Emitter};
use std::sync::Mutex;
#[derive(Default)]
struct JunctionInvite(Mutex<Option<String>>);
fn valid_junction_invite(value: &str) -> bool {
    value.len() <= 8192 && value.starts_with("plumdeck-junction://join?") && !value.chars().any(char::is_control)
}
#[tauri::command]
fn junction_pending_invite(state: tauri::State<JunctionInvite>) -> Option<String> {
    state.0.lock().ok()?.take()
}
use tauri_plugin_shell::process::CommandEvent;
use tauri_plugin_shell::ShellExt;

mod assist;
mod dj_engine;

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        // 開発者ツールを有効化 (リリースビルドでもF12/右クリックで開けるようにする)
        .plugin(tauri_plugin_devtools::init())
        .plugin(tauri_plugin_updater::Builder::new().build())
        .plugin(tauri_plugin_process::init())
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_fs::init())
        .plugin(tauri_plugin_http::init())
        .plugin(tauri_plugin_drag::init())
        .menu(|handle| {
            let menu = Menu::new(handle)?;

            #[cfg(target_os = "macos")]
            {
                let app_menu = Submenu::new(handle, "plumdeck", true)?;
                app_menu.append(&PredefinedMenuItem::hide(handle, None)?)?;
                app_menu.append(&PredefinedMenuItem::hide_others(handle, None)?)?;
                app_menu.append(&PredefinedMenuItem::quit(handle, None)?)?;
                menu.append(&app_menu)?;
            }

            let edit_menu = Submenu::new(handle, "Edit", true)?;
            edit_menu.append(&PredefinedMenuItem::undo(handle, None)?)?;
            edit_menu.append(&PredefinedMenuItem::redo(handle, None)?)?;
            edit_menu.append(&PredefinedMenuItem::separator(handle)?)?;
            edit_menu.append(&PredefinedMenuItem::cut(handle, None)?)?;
            edit_menu.append(&PredefinedMenuItem::copy(handle, None)?)?;
            edit_menu.append(&PredefinedMenuItem::paste(handle, None)?)?;
            edit_menu.append(&PredefinedMenuItem::select_all(handle, None)?)?;
            menu.append(&edit_menu)?;

            let view_menu = Submenu::new(handle, "View", true)?;
            view_menu.append(&PredefinedMenuItem::fullscreen(handle, None)?)?;
            view_menu.append(&MenuItem::with_id(
                handle,
                "toggle_devtools",
                "Toggle Developer Tools",
                true,
                None::<&str>,
            )?)?;
            menu.append(&view_menu)?;

            Ok(menu)
        })
        .on_window_event(|window, event| {
            if let tauri::WindowEvent::CloseRequested { api, .. } = event {
                if window.state::<Arc<dj_engine::EngineSupervisor>>().junction_active().unwrap_or(true) {
                    api.prevent_close();
                    let _ = window.emit("junction://close-blocked", ());
                }
            }
        })
        .on_menu_event(|app, event| {
            if event.id() == "toggle_devtools" {
                if let Some(window) = app.get_webview_window("main") {
                    if window.is_devtools_open() {
                        window.close_devtools();
                    } else {
                        window.open_devtools();
                    }
                }
            }
        })
        .manage(Arc::new(dj_engine::EngineSupervisor::new()))
        // Assist mode only reads; both of these are passive state holders.
        .manage(JunctionInvite::default())
        .manage(assist::AssistState::default())
        .manage(assist::commands::WindowBounds::default())
        .invoke_handler(tauri::generate_handler![
            junction_pending_invite,
            assist::commands::assist_snapshot,
            assist::commands::assist_request_accessibility,
            assist::commands::assist_open_accessibility_settings,
            assist::commands::assist_enter_compact_window,
            assist::commands::assist_exit_compact_window,
            assist::commands::assist_set_always_on_top,
            dj_engine::midi::dj_midi_status,
            dj_engine::midi::dj_midi_send,
            dj_engine::midi::dj_midi_read,
            dj_engine::midi::dj_midi_performance_config,
            dj_engine::midi::dj_jog_display_update,
            dj_engine::commands::dj_engine_status,
            dj_engine::commands::dj_engine_start,
            dj_engine::commands::dj_engine_stop,
            dj_engine::commands::dj_engine_connect,
            dj_engine::commands::dj_engine_send,
            waveform::dj_waveform_tile,
            waveform::dj_waveform_pcm,
            waveform::dj_waveform_manifest,
            dj_engine::commands::junction_command,
            junction_exchange_files::junction_read_exchange_file,
            junction_exchange_files::junction_write_exchange_file,
        ])
        .setup(|app| {
            for arg in env::args().skip(1) { if valid_junction_invite(&arg) { if let Ok(mut pending) = app.state::<JunctionInvite>().0.lock() { *pending = Some(arg); } } }
            app.manage(dj_engine::midi::controller(app.handle().clone()));
            app.manage(dj_engine::jog_display::JogDisplay::new());
            // ネイティブ DJ エンジン（Phase 0 シミュレータ）はオプトイン起動。
            // 既定では起動せず、フロントは「未起動」を受け取って素直に劣化する。
            // Python サイドカーとは独立なので、CI 判定より前に置く。
            if env_flag("PLUMDECK_DJ_ENGINE_AUTOSTART") {
                let handle = app.handle().clone();
                std::thread::spawn(move || {
                    let supervisor = handle
                        .state::<Arc<dj_engine::EngineSupervisor>>()
                        .inner()
                        .clone();
                    match supervisor.start(&handle, None, None) {
                        Ok(status) => println!(
                            "[dj-engine] 自動起動しました running={} simulated={}",
                            status.running, status.simulated
                        ),
                        Err(error) => eprintln!("[dj-engine] 自動起動に失敗しました: {}", error),
                    }
                });
            }

            // CI環境やビルド時はサイドカーを起動しない
            if env::var("CI").is_ok() || env::var("TAURI_SKIP_SIDECAR").is_ok() {
                println!("Skipping sidecar startup (CI/build environment)");
                return Ok(());
            }

            // サイドカーの起動
            // 本番環境（リリースビルド）では競合しにくいポートを使用する
            // 開発環境ではデフォルトの8001を使用
            #[cfg(debug_assertions)]
            let port = "8001";
            #[cfg(not(debug_assertions))]
            let port = "48123"; // 競合しにくいポート番号

            let sidecar_command = app
                .shell()
                .sidecar("plumdeck-server")
                .map_err(|e| {
                    eprintln!("Failed to create sidecar command: {}", e);
                    e
                })?
                .env("PLUMDECK_PORT", port);

            // コマンドの実行結果を詳細にログ出力
            println!("Attempting to spawn sidecar with port: {}", port);

            let (mut _rx, _child) = sidecar_command.spawn().map_err(|e| {
                eprintln!("Failed to spawn sidecar: {}", e);
                e
            })?;

            // 非同期でログを出力するスレッドを作成（デバッグ用）
            tauri::async_runtime::spawn(async move {
                while let Some(event) = _rx.recv().await {
                    if let CommandEvent::Stdout(line) = event {
                        println!("[PY]: {}", String::from_utf8_lossy(&line));
                    } else if let CommandEvent::Stderr(line) = event {
                        eprintln!("[PY ERR]: {}", String::from_utf8_lossy(&line));
                    }
                }
            });

            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while building tauri application")
        .run(|app, event| {
            if let tauri::RunEvent::ExitRequested { ref api, .. } = event {
                if app.state::<Arc<dj_engine::EngineSupervisor>>().junction_active().unwrap_or(true) {
                    api.prevent_exit(); let _ = app.emit("junction://close-blocked", ());
                }
            }
            #[cfg(any(target_os = "macos", target_os = "ios"))]
            if let tauri::RunEvent::Opened { urls } = event {
                for url in urls { let value = url.to_string(); if valid_junction_invite(&value) {
                    if let Ok(mut pending) = app.state::<JunctionInvite>().0.lock() { *pending = Some(value.clone()); }
                    let _ = app.emit("junction://invite", value);
                    if let Some(window) = app.get_webview_window("main") { let _ = window.set_focus(); }
                }}
            }
        });
}

fn env_flag(name: &str) -> bool {
    env::var(name)
        .ok()
        .map(|value| {
            matches!(
                value.trim().to_ascii_lowercase().as_str(),
                "1" | "true" | "yes" | "on"
            )
        })
        .unwrap_or(false)
}
