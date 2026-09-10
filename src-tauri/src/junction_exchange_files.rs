//! Explicit user-selected exchange files. Invitations and responses stay out of
//! application logs, localStorage and the library database.
use std::{fs, io::{Read, Write}, path::Path, time::{SystemTime, UNIX_EPOCH}};
const MAX_BYTES: usize = 128 * 1024;
static SEQUENCE: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);
fn sequence() -> u64 { SEQUENCE.fetch_add(1, std::sync::atomic::Ordering::Relaxed) }
fn read_exchange(path: &Path) -> Result<String, String> {
    let metadata = fs::symlink_metadata(path).map_err(|_| "ファイルを開けません。場所と読み取り権限を確認してください")?;
    if !metadata.is_file() || metadata.file_type().is_symlink() { return Err("招待・返答を保存した通常のファイルを選択してください".into()); }
    if metadata.len() > MAX_BYTES as u64 { return Err("ファイルが大きすぎます。招待・返答は128KB以内です".into()); }
    let file = fs::File::open(path).map_err(|_| "ファイルを開けません")?;
    let mut bytes = Vec::new();
    file.take(MAX_BYTES as u64 + 1).read_to_end(&mut bytes).map_err(|_| "ファイルを読み込めません")?;
    if bytes.len() > MAX_BYTES { return Err("ファイルが大きすぎます。招待・返答は128KB以内です".into()); }
    let text = String::from_utf8(bytes).map_err(|_| "文字形式が違います。plumdeckから書き出したファイルを選択してください")?;
    if text.contains('\0') { return Err("招待・返答の形式が違います".into()); }
    Ok(text.trim_start_matches('\u{feff}').to_owned())
}
fn write_exchange(path: &Path, text: &str) -> Result<(), String> {
    if text.is_empty() || text.len() > MAX_BYTES || text.contains('\0') { return Err("保存する招待・返答が空、または大きすぎます".into()); }
    if let Ok(metadata) = fs::symlink_metadata(path) {
        if !metadata.is_file() || metadata.file_type().is_symlink() { return Err("別の保存先を選択してください".into()); }
    }
    let directory = path.parent().filter(|p| p.is_dir()).ok_or("保存先のフォルダーが見つかりません")?;
    let nonce = SystemTime::now().duration_since(UNIX_EPOCH).map_err(|_| "時刻を確認できません")?.as_nanos();
    let temporary = directory.join(format!(".plumdeck-exchange-{}-{nonce}-{}.tmp", std::process::id(), sequence()));
    let mut created = false;
    let result = (|| -> Result<(), String> {
        let mut options = fs::OpenOptions::new(); options.write(true).create_new(true);
        #[cfg(unix)] { use std::os::unix::fs::OpenOptionsExt; options.mode(0o600); }
        let mut file = options.open(&temporary).map_err(|_| "保存先へ書き込めません。場所と権限を確認してください")?;
        created = true;
        file.write_all(text.as_bytes()).and_then(|_| file.sync_all()).map_err(|_| "保存できません。空き容量を確認してください")?;
        fs::rename(&temporary, path).map_err(|_| "ファイルを保存できません。別の保存先を選択してください")?;
        Ok(())
    })();
    if created && result.is_err() { let _ = fs::remove_file(&temporary); }
    result
}
#[tauri::command]
pub async fn junction_read_exchange_file(path: String) -> Result<String, String> {
    tauri::async_runtime::spawn_blocking(move || read_exchange(Path::new(&path))).await.map_err(|_| "ファイルの読み込み処理が終了しました".to_string())?
}
#[tauri::command]
pub async fn junction_write_exchange_file(path: String, text: String) -> Result<(), String> {
    tauri::async_runtime::spawn_blocking(move || write_exchange(Path::new(&path), &text)).await.map_err(|_| "ファイルの保存処理が終了しました".to_string())?
}
#[cfg(test)]
mod tests {
    use super::*;
    fn directory() -> std::path::PathBuf {
        let p = std::env::temp_dir().join(format!("plumdeck-exchange-test-{}-{}-{}", std::process::id(), SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_nanos(), sequence()));
        fs::create_dir(&p).unwrap(); p
    }
    #[test]
    fn explicit_file_round_trip_and_atomic_replacement() {
        let dir=directory(); let p=dir.join("招待.djct");
        write_exchange(&p,"初回の招待").unwrap(); write_exchange(&p,"新しい返答").unwrap();
        assert_eq!(read_exchange(&p).unwrap(),"新しい返答"); assert_eq!(fs::read_dir(&dir).unwrap().count(),1);
        #[cfg(unix)] { use std::os::unix::fs::PermissionsExt; assert_eq!(fs::metadata(&p).unwrap().permissions().mode() & 0o777,0o600); }
        fs::remove_dir_all(dir).unwrap();
    }
    #[test]
    fn file_limits_and_binary_content_are_rejected() {
        let dir=directory(); let p=dir.join("bad.djct");
        fs::write(&p, vec![b'x'; MAX_BYTES+1]).unwrap(); assert!(read_exchange(&p).is_err());
        fs::write(&p,[0xff]).unwrap(); assert!(read_exchange(&p).is_err());
        assert!(write_exchange(&p,"\0").is_err()); assert!(read_exchange(&dir).is_err());
        fs::remove_dir_all(dir).unwrap();
    }
    #[cfg(unix)]
    #[test]
    fn symbolic_links_are_not_followed() {
        let dir=directory(); let p=dir.join("original");let link=dir.join("link");fs::write(&p,"keep").unwrap();std::os::unix::fs::symlink(&p,&link).unwrap();
        assert!(read_exchange(&link).is_err());assert!(write_exchange(&link,"changed").is_err());assert_eq!(fs::read_to_string(&p).unwrap(),"keep");fs::remove_dir_all(dir).unwrap();
    }
}
