//! 実 WKWebView (wry) で波形 renderer を長時間動かすだけの検証アプリ。
//! ユーザーのライブラリ・音声デバイス・Tauri コマンドには触れない。
//! Vite (既定 http://127.0.0.1:1420) が同じリポジトリを配信している必要がある。
//!
//!   cargo build --manifest-path src-tauri/Cargo.toml --example waveform_validation
//!   PLUMDECK_VALIDATION_SECONDS=600 src-tauri/target/debug/examples/waveform_validation
//!
//! ページが計測を終えると WAVEFORM_VALIDATION <json> を stdout へ 1 行出して終了する。
use std::{env, process, time::{Duration, Instant}};
use tao::{
    dpi::LogicalSize,
    event::{Event, StartCause, WindowEvent},
    event_loop::{ControlFlow, EventLoopBuilder},
    window::WindowBuilder,
};
use wry::WebViewBuilder;

enum UserEvent {
    Report(String),
}

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let seconds: u64 = env::var("PLUMDECK_VALIDATION_SECONDS").ok().and_then(|value| value.parse().ok()).unwrap_or(600);
    let base = env::var("PLUMDECK_VALIDATION_URL").unwrap_or_else(|_| "http://127.0.0.1:1420/tools/waveform-validation.html".to_string());
    let surfaces: u32 = env::var("PLUMDECK_VALIDATION_SURFACES").ok().and_then(|value| value.parse().ok()).unwrap_or(4);
    let url = format!("{base}?seconds={seconds}&surfaces={surfaces}");

    let event_loop = EventLoopBuilder::<UserEvent>::with_user_event().build();
    let proxy = event_loop.create_proxy();
    // WKWebView は隠れたウィンドウの requestAnimationFrame を止めるため、
    // 計測中は前面に固定する。そうしないと 10 分の描画計測が成立しない。
    let window = WindowBuilder::new()
        .with_title("plumdeck waveform validation")
        .with_inner_size(LogicalSize::new(1240.0, 640.0))
        .with_always_on_top(true)
        .with_focused(true)
        .build(&event_loop)?;
    window.set_focus();
    let webview = WebViewBuilder::new()
        .with_url(&url)
        .with_ipc_handler(move |request| {
            let _ = proxy.send_event(UserEvent::Report(request.body().clone()));
        })
        .build(&window)?;

    // ページ側の計測時間に加え、読み込みと後処理の余裕を持った打ち切り時刻。
    let deadline = Instant::now() + Duration::from_secs(seconds + 120);
    event_loop.run(move |event, _, control_flow| {
        let _ = &webview;
        *control_flow = ControlFlow::WaitUntil(Instant::now() + Duration::from_secs(1));
        match event {
            Event::NewEvents(StartCause::Init) => eprintln!("waveform_validation: loading {url}"),
            Event::UserEvent(UserEvent::Report(body)) => {
                if let Some(rest) = body.strip_prefix("WAVEFORM_VALIDATION ") {
                    println!("WAVEFORM_VALIDATION {rest}");
                    let passed = serde_json::from_str::<serde_json::Value>(rest).ok()
                        .and_then(|v| v["passed"].as_bool()).unwrap_or(false);
                    process::exit(if passed { 0 } else { 4 });
                }
                // 進捗と JS 例外は診断用。計測結果ではないので stderr に出す。
                eprintln!("waveform_validation: {body}");
                if body.starts_with("VALIDATION_ERROR ") {
                    process::exit(3);
                }
            }
            Event::WindowEvent { event: WindowEvent::CloseRequested, .. } => {
                eprintln!("waveform_validation: window closed before the measurement finished");
                process::exit(2);
            }
            _ => {}
        }
        if Instant::now() >= deadline {
            eprintln!("waveform_validation: timed out after {}s without a report", seconds + 120);
            process::exit(1);
        }
    });
}
