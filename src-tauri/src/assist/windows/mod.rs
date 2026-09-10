//! Read-only Windows UI Automation and open-file observation, in a bounded child.
use super::{AssistSnapshot, decks};
use std::{io::{Read, BufRead, BufReader, Write}, os::windows::process::CommandExt, process::{Child, ChildStdin, Command, Stdio},
    sync::Mutex, time::{Duration, Instant, SystemTime, UNIX_EPOCH}};
use serde::Deserialize;

#[derive(Default)]
struct Observer {
    last: Option<(Instant, AssistSnapshot)>,
    worker: Option<ProbeWorker>,
}
#[derive(Default)]
pub struct AssistState { observer: Mutex<Observer> }
#[derive(Deserialize)]
struct Node { role: String, value: String, x:f64, y:f64, width:f64, height:f64 }
#[derive(Deserialize)]
#[serde(rename_all="camelCase")]
struct Probe {
    running: bool,
    error: Option<String>,
    app_path: Option<String>,
    #[serde(default)] right: f64,
    #[serde(default)] nodes: Vec<Node>,
    #[serde(default)] paths: Vec<String>,
    paths_error: Option<String>,
    #[serde(default)] truncated: bool,
}
impl AssistState {
    pub fn snapshot(&self) -> AssistSnapshot {
        let mut observer=self.observer.lock().unwrap_or_else(|e| e.into_inner());
        if let Some((at, snapshot)) = observer.last.as_ref() {
            if at.elapsed()<Duration::from_secs(2) { return snapshot.clone(); }
        }
        let mut snapshot=AssistSnapshot { supported:true, permission_granted:true,
            captured_at_ms:SystemTime::now().duration_since(UNIX_EPOCH).unwrap_or_default().as_millis() as u64,
            ..Default::default() };
        let result=(|| {
            if observer.worker.is_none() { observer.worker=Some(ProbeWorker::start()?); }
            observer.worker.as_mut().unwrap().snapshot()
        })();
        if result.is_err() { observer.worker=None; }
        match result {
            Ok(result) => {
                snapshot.app_running=result.running;
                snapshot.app_path=result.app_path;
                snapshot.open_audio_paths=result.paths;
                snapshot.open_paths_error=result.paths_error;
                let nodes=result.nodes.into_iter().map(|n| decks::Node {role:n.role,value:n.value,
                    x:n.x,y:n.y,width:n.width,height:n.height}).collect::<Vec<_>>();
                let (observations,warnings)=decks::parse_decks(&nodes,result.right);
                snapshot.warnings=warnings;
                if !result.truncated { snapshot.decks=observations; }
                snapshot.layout_hint=decks::layout_hint(&nodes);
                snapshot.signature=decks::signature(&snapshot.decks);
                if !result.running {
                    snapshot.unavailable_reason=Some("rekordbox のウィンドウが見つかりません".into());
                } else if snapshot.decks.is_empty() {
                    snapshot.unavailable_reason=Some("rekordbox の PERFORMANCE 画面を表示してください。両アプリを同じユーザー・権限で起動してください".into());
                }
                if result.truncated { snapshot.warnings.push("UI読み取りの上限に達しました".into()); }
            }
            Err(error) => snapshot.unavailable_reason=Some(error),
        }
        observer.last=Some((Instant::now(),snapshot.clone()));
        snapshot
    }
    pub fn request_permission(&self) -> bool { true }
    pub fn open_permission_settings(&self) -> Result<(), String> {
        // Windows UI Automation requires no global Accessibility permission.
        Ok(())
    }
}
struct ProbeWorker {
    child: Child,
    input: ChildStdin,
    output: std::sync::mpsc::Receiver<Result<Vec<u8>,String>>,
}
impl Drop for ProbeWorker {
    fn drop(&mut self) { let _=self.child.kill(); let _=self.child.wait(); }
}
impl ProbeWorker {
fn start() -> Result<Self,String> {
    let system=std::env::var_os("SystemRoot").ok_or("Windows システムフォルダーを取得できません")?;
    let shell=std::path::PathBuf::from(system).join("System32/WindowsPowerShell/v1.0/powershell.exe");
    let mut child=Command::new(shell).args(["-NoLogo","-NoProfile","-NonInteractive","-Command",include_str!("probe.ps1")])
        .creation_flags(0x08000000).stdin(Stdio::piped()).stdout(Stdio::piped()).stderr(Stdio::null())
        .spawn().map_err(|e|format!("Windows UI 読み取りを開始できません: {e}"))?;
        let input=child.stdin.take().expect("piped stdin");
        let output=child.stdout.take().expect("piped stdout");
        let (send,receive)=std::sync::mpsc::sync_channel(1);
        std::thread::spawn(move || {
            let mut reader=BufReader::new(output);
            loop {
                let mut bytes=Vec::new();
                match (&mut reader).take(4*1024*1024+1).read_until(b'\n', &mut bytes) {
                    Ok(0) => break,
                    Ok(_) if bytes.len()<=4*1024*1024 => { if send.send(Ok(bytes)).is_err() { break; } }
                    Ok(_) => { let _=send.send(Err("UI 読み取りが上限を超えました".into())); break; }
                    Err(error) => { let _=send.send(Err(error.to_string())); break; }
                }
            }
        });
        Ok(Self {child,input,output:receive})
}
fn snapshot(&mut self) -> Result<Probe,String> {
        self.input.write_all(b"snapshot\n").and_then(|_|self.input.flush()).map_err(|e|e.to_string())?;
        // The first observation may cold-load .NET/UI Automation. Subsequent
        // observations reuse the helper and compiled types; UI traversal itself
        // remains bounded in the script, with an outer watchdog for hung apps.
        let output=self.output.recv_timeout(Duration::from_secs(20)).map_err(|_|"Windows UI 読み取りがタイムアウトしました")??;
        let result: Probe = serde_json::from_slice(&output).map_err(|e|format!("Windows UI 情報を取得できません: {e}"))?;
        if let Some(error) = result.error.as_ref() { return Err(format!("Windows UI 読み取り: {error}")); }
        Ok(result)
}
}

#[cfg(test)]
mod tests {
    #[test]
    fn builtin_windows_probe_runs_without_external_runtime() {
        let mut worker=super::ProbeWorker::start().expect("Windows observation helper must start");
        let result=worker.snapshot().expect("Windows UI Automation helper must return JSON");
        if !result.running { assert!(result.nodes.is_empty()); assert!(result.paths.is_empty()); }
        let second=worker.snapshot().expect("A second observation must reuse the same helper");
        if !second.running { assert!(second.nodes.is_empty()); }
    }
}
