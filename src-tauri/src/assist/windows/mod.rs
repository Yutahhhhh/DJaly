//! Read-only Windows UI Automation and open-file observation, in a bounded child.
use super::{AssistSnapshot, decks};
use std::{io::{Read, Write}, os::windows::process::CommandExt, process::{Command, Stdio},
    sync::Mutex, time::{Duration, Instant, SystemTime, UNIX_EPOCH}};
use serde::Deserialize;

#[derive(Default)]
pub struct AssistState { last: Mutex<Option<(Instant, AssistSnapshot)>> }
#[derive(Deserialize)]
struct Node { role: String, value: String, x:f64, y:f64, width:f64, height:f64 }
#[derive(Deserialize)]
#[serde(rename_all="camelCase")]
struct Probe {
    running: bool,
    app_path: Option<String>,
    #[serde(default)] right: f64,
    #[serde(default)] nodes: Vec<Node>,
    #[serde(default)] paths: Vec<String>,
    paths_error: Option<String>,
    #[serde(default)] truncated: bool,
}
impl AssistState {
    pub fn snapshot(&self) -> AssistSnapshot {
        let mut last=self.last.lock().unwrap_or_else(|e| e.into_inner());
        if let Some((at, snapshot)) = last.as_ref() {
            if at.elapsed()<Duration::from_secs(2) { return snapshot.clone(); }
        }
        let mut snapshot=AssistSnapshot { supported:true, permission_granted:true,
            captured_at_ms:SystemTime::now().duration_since(UNIX_EPOCH).unwrap_or_default().as_millis() as u64,
            ..Default::default() };
        match probe() {
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
        *last=Some((Instant::now(),snapshot.clone()));
        snapshot
    }
    pub fn request_permission(&self) -> bool { true }
    pub fn open_permission_settings(&self) -> Result<(), String> {
        // Windows UI Automation requires no global Accessibility permission.
        Ok(())
    }
}
fn probe() -> Result<Probe,String> {
    let system=std::env::var_os("SystemRoot").ok_or("Windows システムフォルダーを取得できません")?;
    let shell=std::path::PathBuf::from(system).join("System32/WindowsPowerShell/v1.0/powershell.exe");
    let mut child=Command::new(shell).args(["-NoLogo","-NoProfile","-NonInteractive","-Command","-"])
        .creation_flags(0x08000000).stdin(Stdio::piped()).stdout(Stdio::piped()).stderr(Stdio::null())
        .spawn().map_err(|e|format!("Windows UI 読み取りを開始できません: {e}"))?;
    let result=(|| {
        child.stdin.take().ok_or("UI 読み取りの入力がありません")?.write_all(include_bytes!("probe.ps1")).map_err(|e|e.to_string())?;
        let output=child.stdout.take().ok_or("UI 読み取りの出力がありません")?;
        let (send,receive)=std::sync::mpsc::sync_channel(1);
        std::thread::spawn(move || {
            let mut bytes=Vec::new();
            let result=output.take(4*1024*1024+1).read_to_end(&mut bytes).map(|_|bytes);
            let _=send.send(result);
        });
        let output=receive.recv_timeout(Duration::from_secs(8)).map_err(|_|"Windows UI 読み取りがタイムアウトしました")?
            .map_err(|e|e.to_string())?;
        if output.len()>4*1024*1024 { return Err("UI 読み取りが上限を超えました".into()); }
        serde_json::from_slice(&output).map_err(|e|format!("Windows UI 情報を取得できません: {e}"))
    })();
    let _=child.kill(); let _=child.wait();
    result
}

#[cfg(test)]
mod tests {
    #[test]
    fn builtin_windows_probe_runs_without_external_runtime() {
        let result=super::probe().expect("Windows UI Automation helper must start and return JSON");
        if !result.running { assert!(result.nodes.is_empty()); assert!(result.paths.is_empty()); }
    }
}
