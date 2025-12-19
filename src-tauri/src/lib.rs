use tauri_plugin_shell::ShellExt;
use tauri_plugin_shell::process::CommandEvent;
use std::env;

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        // 開発者ツールを有効化 (リリースビルドでもF12/右クリックで開けるようにする)
        .plugin(tauri_plugin_devtools::init()) 
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
            // 本番環境（リリースビルド）では競合しにくいポートを使用する
            // 開発環境ではデフォルトの8001を使用
            #[cfg(debug_assertions)]
            let port = "8001";
            #[cfg(not(debug_assertions))]
            let port = "48123"; // 競合しにくいポート番号

            let sidecar_command = app.shell().sidecar("djaly-server")
                .unwrap()
                .env("DJALY_PORT", port);
            
            // コマンドの実行結果を詳細にログ出力
            println!("Attempting to spawn sidecar with port: {}", port);

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