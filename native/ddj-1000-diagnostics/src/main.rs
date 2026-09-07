use ddj_1000_diagnostics::{human_report, monitor_source, scan};
use std::process::ExitCode;

fn usage() -> &'static str {
    "Usage:\n  ddj-1000-diagnostics scan [--json]\n  ddj-1000-diagnostics monitor --source-id <CoreMIDI-unique-id> [--seconds <1..3600>] [--json]\n\nThe tool is read-only: it has no audio-output or MIDI-transmit operation."
}

fn run() -> Result<(), String> {
    let args: Vec<String> = std::env::args().skip(1).collect();
    match args.first().map(String::as_str) {
        Some("scan") => {
            if args.len() > 2 || (args.len() == 2 && args[1] != "--json") {
                return Err(usage().into());
            }
            let report = scan()?;
            if args.get(1).map(String::as_str) == Some("--json") {
                println!(
                    "{}",
                    serde_json::to_string_pretty(&report).map_err(|e| e.to_string())?
                );
            } else {
                print!("{}", human_report(&report));
            }
            Ok(())
        }
        Some("monitor") => {
            let mut source_id = None;
            let mut seconds = 10_u64;
            let mut json = false;
            let mut i = 1;
            while i < args.len() {
                match args[i].as_str() {
                    "--source-id" => {
                        i += 1;
                        source_id = Some(
                            args.get(i)
                                .ok_or("--source-id requires a value")?
                                .parse::<i32>()
                                .map_err(|_| "--source-id must be an i32 CoreMIDI unique ID")?,
                        );
                    }
                    "--seconds" => {
                        i += 1;
                        seconds = args
                            .get(i)
                            .ok_or("--seconds requires a value")?
                            .parse::<u64>()
                            .map_err(|_| "--seconds must be an integer")?;
                        if !(1..=3600).contains(&seconds) {
                            return Err("--seconds must be between 1 and 3600".into());
                        }
                    }
                    "--json" => json = true,
                    unknown => {
                        return Err(format!("unknown monitor option: {unknown}\n{}", usage()))
                    }
                }
                i += 1;
            }
            let source_id = source_id.ok_or_else(|| {
                "monitor requires exact endpoint selection: --source-id <unique-id> from scan"
                    .to_string()
            })?;
            monitor_source(source_id, seconds, json)
        }
        Some("help" | "--help" | "-h") => {
            println!("{}", usage());
            Ok(())
        }
        _ => Err(usage().into()),
    }
}

fn main() -> ExitCode {
    match run() {
        Ok(()) => ExitCode::SUCCESS,
        Err(error) => {
            eprintln!("error: {error}");
            ExitCode::FAILURE
        }
    }
}
