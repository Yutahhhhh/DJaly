//! DJaly ネイティブ DJ エンジンの **シミュレータ** 実行ファイル。
//!
//! stdin から NDJSON コマンドを読み、stdout へ NDJSON メッセージを書く。
//! ログは stderr のみ。音声デバイスは開かず、音は一切出ない。
//!
//! ```text
//! dj-engine-sim [--deterministic] [--engine-id=<id>] [--tick-ms=<n>]
//!               [--load-latency-ms=<n>] [--position-interval-ms=<n>]
//!               [--meters-interval-ms=<n>]
//! ```

use std::io::{self, BufRead};
use std::sync::{Arc, Mutex, MutexGuard};
use std::thread;
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

use dj_engine_host::runtime::{self, Runtime};
use dj_engine_host::{Engine, EngineConfig};

struct Args {
    deterministic: bool,
    engine_id: Option<String>,
    tick_ms: u64,
    load_latency_ms: f64,
    position_interval_ms: f64,
    meters_interval_ms: f64,
}

impl Default for Args {
    fn default() -> Self {
        Args {
            deterministic: false,
            engine_id: None,
            tick_ms: 20,
            load_latency_ms: 120.0,
            position_interval_ms: 50.0,
            meters_interval_ms: 100.0,
        }
    }
}

fn main() {
    let args = match parse_args() {
        Ok(args) => args,
        Err(message) => {
            eprintln!("[dj-engine-sim] {message}");
            print_usage();
            std::process::exit(2);
        }
    };

    let engine_id = args.engine_id.clone().unwrap_or_else(default_engine_id);

    let config = EngineConfig {
        engine_id: engine_id.clone(),
        version: env!("CARGO_PKG_VERSION").to_string(),
        implementation: "simulator".to_string(),
        deterministic: args.deterministic,
        load_latency_ms: args.load_latency_ms,
        position_interval_ms: args.position_interval_ms,
        meters_interval_ms: args.meters_interval_ms,
    };

    let engine_runtime = Arc::new(Mutex::new(Runtime::new(Engine::new(config))));
    let writer = Arc::new(Mutex::new(io::stdout()));
    // Sequence allocation and stdout publication must be one ordered operation
    // across the wall-clock tick and stdin threads.
    let output_order = Arc::new(Mutex::new(()));
    let started = Instant::now();

    eprintln!(
        "[dj-engine-sim] 起動しました engineId={} deterministic={} pid={}",
        engine_id,
        args.deterministic,
        std::process::id()
    );

    // 決定論モードでは壁時計を使わない。時間は sim.advanceTime でのみ進む。
    if !args.deterministic {
        let tick_runtime = Arc::clone(&engine_runtime);
        let tick_writer = Arc::clone(&writer);
        let tick_order = Arc::clone(&output_order);
        let tick_ms = args.tick_ms;
        thread::spawn(move || loop {
            thread::sleep(Duration::from_millis(tick_ms));
            let now_ms = elapsed_ms(started);
            let _order = lock(&tick_order);
            let messages = {
                let mut guard = lock(&tick_runtime);
                guard.tick(now_ms)
            };
            if messages.is_empty() {
                continue;
            }
            let mut out = lock(&tick_writer);
            if let Err(error) = runtime::write_messages(&mut *out, &messages) {
                eprintln!("[dj-engine-sim] stdout への書き込みに失敗しました: {error}");
                break;
            }
        });
    }

    let stdin = io::stdin();
    for line in stdin.lock().lines() {
        let line = match line {
            Ok(line) => line,
            Err(error) => {
                eprintln!("[dj-engine-sim] stdin の読み取りに失敗しました: {error}");
                break;
            }
        };
        let now_ms = if args.deterministic {
            None
        } else {
            Some(elapsed_ms(started))
        };
        let _order = lock(&output_order);
        let messages = {
            let mut guard = lock(&engine_runtime);
            guard.process(now_ms, &line)
        };
        if messages.is_empty() {
            continue;
        }
        let mut out = lock(&writer);
        if let Err(error) = runtime::write_messages(&mut *out, &messages) {
            eprintln!("[dj-engine-sim] stdout への書き込みに失敗しました: {error}");
            break;
        }
    }

    eprintln!("[dj-engine-sim] stdin が閉じられたので終了します");
}

fn elapsed_ms(started: Instant) -> f64 {
    started.elapsed().as_secs_f64() * 1000.0
}

/// Mutex の poison でプロセスを落とさない。状態は保持したまま続行する。
fn lock<T>(mutex: &Mutex<T>) -> MutexGuard<'_, T> {
    mutex
        .lock()
        .unwrap_or_else(|poisoned| poisoned.into_inner())
}

fn default_engine_id() -> String {
    let pid = std::process::id();
    let nanos = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|delta| delta.as_nanos())
        .unwrap_or(0);
    format!("eng-{pid:x}-{:x}", nanos & 0xffff_ffff)
}

fn parse_args() -> Result<Args, String> {
    let mut args = Args::default();
    let mut iter = std::env::args().skip(1);
    while let Some(argument) = iter.next() {
        let (key, inline) = match argument.split_once('=') {
            Some((key, value)) => (key.to_string(), Some(value.to_string())),
            None => (argument.clone(), None),
        };
        match key.as_str() {
            "--help" | "-h" => {
                print_usage();
                std::process::exit(0);
            }
            "--deterministic" => args.deterministic = true,
            "--engine-id" => args.engine_id = Some(take_value(&key, inline, &mut iter)?),
            "--tick-ms" => {
                let raw = take_value(&key, inline, &mut iter)?;
                args.tick_ms = raw
                    .parse::<u64>()
                    .map_err(|_| format!("{key} は整数である必要があります"))?;
            }
            "--load-latency-ms" => {
                args.load_latency_ms = parse_f64(&key, take_value(&key, inline, &mut iter)?)?;
            }
            "--position-interval-ms" => {
                args.position_interval_ms = parse_f64(&key, take_value(&key, inline, &mut iter)?)?;
            }
            "--meters-interval-ms" => {
                args.meters_interval_ms = parse_f64(&key, take_value(&key, inline, &mut iter)?)?;
            }
            other => return Err(format!("未知の引数: {other}")),
        }
    }

    if args.tick_ms == 0 {
        return Err("--tick-ms は 1 以上である必要があります".to_string());
    }
    if args.load_latency_ms < 0.0 {
        return Err("--load-latency-ms は 0 以上である必要があります".to_string());
    }
    if args.position_interval_ms <= 0.0 || args.meters_interval_ms <= 0.0 {
        return Err("通知間隔は正の値である必要があります".to_string());
    }
    Ok(args)
}

fn take_value(
    key: &str,
    inline: Option<String>,
    iter: &mut impl Iterator<Item = String>,
) -> Result<String, String> {
    match inline {
        Some(value) => Ok(value),
        None => iter.next().ok_or_else(|| format!("{key} には値が必要です")),
    }
}

fn parse_f64(key: &str, raw: String) -> Result<f64, String> {
    let value = raw
        .parse::<f64>()
        .map_err(|_| format!("{key} は数値である必要があります"))?;
    if !value.is_finite() {
        return Err(format!("{key} は有限の数値である必要があります"));
    }
    Ok(value)
}

fn print_usage() {
    eprintln!(
        "dj-engine-sim — DJaly ネイティブエンジンのシミュレータ（音は出ません）\n\
         \n\
         使い方: dj-engine-sim [オプション]\n\
         \n\
         オプション:\n\
         \x20 --deterministic            壁時計を使わず sim.advanceTime でのみ時間を進める\n\
         \x20 --engine-id=<id>           エンジンインスタンス ID を固定する（テスト用）\n\
         \x20 --tick-ms=<n>              壁時計モードのティック間隔（既定: 20）\n\
         \x20 --load-latency-ms=<n>      非同期ロードの模擬所要時間（既定: 120）\n\
         \x20 --position-interval-ms=<n> 再生位置通知の間隔（既定: 50）\n\
         \x20 --meters-interval-ms=<n>   メーター通知の既定間隔（既定: 100）"
    );
}
