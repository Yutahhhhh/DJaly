use std::process::Command;

fn binary() -> Command {
    Command::new(env!("CARGO_BIN_EXE_ddj-1000-diagnostics"))
}

#[test]
fn help_states_the_read_only_boundary() {
    let output = binary().arg("--help").output().unwrap();
    assert!(output.status.success());
    let stdout = String::from_utf8(output.stdout).unwrap();
    assert!(stdout.contains("no audio-output or MIDI-transmit operation"));
}

#[test]
fn monitor_requires_an_exact_source_id_before_touching_coremidi() {
    let output = binary().arg("monitor").output().unwrap();
    assert!(!output.status.success());
    let stderr = String::from_utf8(output.stderr).unwrap();
    assert!(stderr.contains("monitor requires exact endpoint selection"));
}

#[test]
fn monitor_duration_is_bounded() {
    let output = binary()
        .args(["monitor", "--source-id", "123", "--seconds", "0"])
        .output()
        .unwrap();
    assert!(!output.status.success());
    let stderr = String::from_utf8(output.stderr).unwrap();
    assert!(stderr.contains("between 1 and 3600"));
}
