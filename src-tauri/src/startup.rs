use serde::{Deserialize, Serialize};
use std::sync::Mutex;
use tauri::{Emitter, Manager};

#[derive(Clone, Debug, Deserialize, Serialize)]
pub struct Progress {
    pub stage: String,
    pub label: String,
    pub completed: u8,
    pub total: u8,
    pub error: Option<String>,
}

impl Default for Progress {
    fn default() -> Self {
        Self { stage: "launch".into(), label: "解析サービスを起動しています".into(),
            completed: 0, total: 5, error: None }
    }
}

#[derive(Default)]
pub struct StartupState(pub Mutex<Progress>);

pub fn parse(line: &[u8]) -> Option<Progress> {
    let value = std::str::from_utf8(line).ok()?.trim().strip_prefix("PLUMDECK_STARTUP:")?;
    let progress: Progress = serde_json::from_str(value).ok()?;
    if progress.total != 5 || progress.completed > 5 || progress.label.len() > 1024 {
        return None;
    }
    Some(progress)
}

pub fn publish(app: &tauri::AppHandle, progress: Progress) {
    if let Ok(mut current) = app.state::<StartupState>().0.lock() {
        *current = progress.clone();
    }
    let _ = app.emit("backend://startup", progress);
}

pub fn fail(app: &tauri::AppHandle, error: String) {
    let mut progress = app.state::<StartupState>().0.lock()
        .map(|current| current.clone()).unwrap_or_default();
    progress.error = Some(error);
    publish(app, progress);
}

#[tauri::command]
pub fn backend_startup_status(state: tauri::State<StartupState>) -> Progress {
    state.0.lock().map(|current| current.clone()).unwrap_or_default()
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn reads_structured_stages_and_ignores_logs() {
        assert!(parse(b"Starting server...").is_none());
        assert!(parse(b"PLUMDECK_STARTUP:{invalid}").is_none());
        let value = parse(br#"PLUMDECK_STARTUP:{"stage":"database","label":"Database","completed":3,"total":5}"#).unwrap();
        assert_eq!(value.completed, 3);
        assert!(value.error.is_none());
        assert!(parse(br#"PLUMDECK_STARTUP:{"stage":"x","label":"x","completed":99,"total":5}"#).is_none());
    }
}
