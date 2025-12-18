use tauri_plugin_shell::ShellExt;
use tauri_plugin_shell::process::CommandEvent;
use std::env;

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_updater::Builder::new().build())
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_fs::init())
        .setup(|app| {
            // CI環境やビルド時はサイドカーを起動しない
            if env::var("CI").is_ok() || env::var("TAURI_SKIP_SIDECAR").is_ok() {
                println!("Skipping sidecar startup (CI/build environment)");
                return Ok(());
            }

            // サイドカーの起動
            let sidecar_command = app.shell().sidecar("djaly-server").unwrap();
            
            let (mut _rx, _child) = sidecar_command
                .spawn()
                .expect("Failed to spawn sidecar");

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