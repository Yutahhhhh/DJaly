use std::env;
use std::sync::Arc;
use tauri::menu::{Menu, MenuItem, PredefinedMenuItem, Submenu};
use tauri::Manager;
use tauri_plugin_shell::process::CommandEvent;
use tauri_plugin_shell::ShellExt;

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
        .menu(|handle| {
            let menu = Menu::new(handle)?;

            #[cfg(target_os = "macos")]
            {
                let app_menu = Submenu::new(handle, "Djaly", true)?;
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
        .invoke_handler(tauri::generate_handler![
            dj_engine::commands::dj_engine_status,
            dj_engine::commands::dj_engine_start,
            dj_engine::commands::dj_engine_stop,
            dj_engine::commands::dj_engine_connect,
            dj_engine::commands::dj_engine_send,
        ])
        .setup(|app| {
            // ネイティブ DJ エンジン（Phase 0 シミュレータ）はオプトイン起動。
            // 既定では起動せず、フロントは「未起動」を受け取って素直に劣化する。
            // Python サイドカーとは独立なので、CI 判定より前に置く。
            if env_flag("DJALY_DJ_ENGINE_AUTOSTART") {
                let handle = app.handle().clone();
                std::thread::spawn(move || {
                    let supervisor = handle
                        .state::<Arc<dj_engine::EngineSupervisor>>()
                        .inner()
                        .clone();
                    match supervisor.start(&handle, None) {
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
                .sidecar("djaly-server")
                .map_err(|e| {
                    eprintln!("Failed to create sidecar command: {}", e);
                    e
                })?
                .env("DJALY_PORT", port);

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
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
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
