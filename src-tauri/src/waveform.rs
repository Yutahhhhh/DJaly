//! Read only native-published resources under the app-owned waveform cache.
use std::{fs::File, io::Read, path::PathBuf, sync::Arc, time::Instant};
use serde_json::{json, Value};
use tauri::{AppHandle, Manager, State};
use crate::dj_engine::EngineSupervisor;
pub fn cache_root(app:&AppHandle) -> Result<PathBuf,String> {
    // `HOME` is not normally defined for Windows desktop applications. Use
    // Tauri's platform resolver so this remains ~/Library/Caches on macOS and
    // resolves through the Windows known-folder API on Windows.
    app.path().cache_dir()
        .map(|base|base.join("plumdeck").join("waveform-v2"))
        .map_err(|error|format!("波形キャッシュの保存先を取得できません: {error}"))
}
fn valid_key(key:&str)->bool {key.len()==64 && key.bytes().all(|b|b.is_ascii_digit()||(b'a'..=b'f').contains(&b))}
struct Lease {engine:Arc<EngineSupervisor>,session:String,id:String}
impl Drop for Lease {fn drop(&mut self){let _=self.engine.send(&self.session,"waveform.releaseReadLease",json!({"leaseId":self.id}));}}
fn read_resource(engine:Arc<EngineSupervisor>,session:String,root:PathBuf,key:String,resource:String)->Result<Vec<u8>,String>{
    if !valid_key(&key){return Err("Invalid waveform asset".into());}
    let start=Instant::now();
    let reply=engine.send(&session,"waveform.acquireReadLease",json!({"assetKey":key,"resourceKey":resource}))?;
    let id=reply.data.as_ref().and_then(|d|d["leaseId"].as_str()).ok_or("Waveform resource not ready")?.to_owned();
    let _lease=Lease{engine,session,id};
    let root=root.canonicalize().map_err(|e|e.to_string())?;
    let requested=root.join(&key).join(&resource);
    // Reject each symlink, including an asset directory redirected within root.
    if std::fs::symlink_metadata(root.join(&key)).map_err(|e|e.to_string())?.file_type().is_symlink()
      ||std::fs::symlink_metadata(&requested).map_err(|e|e.to_string())?.file_type().is_symlink(){return Err("Invalid waveform path".into());}
    let path=requested.canonicalize().map_err(|e|e.to_string())?;
    if !path.starts_with(root.join(&key)){return Err("Invalid waveform path".into());}
    if !std::fs::metadata(&path).map_err(|e|e.to_string())?.is_file(){return Err("Invalid waveform resource".into());}
    let mut bytes=Vec::new();File::open(path).map_err(|e|e.to_string())?.take(2*1024*1024+65).read_to_end(&mut bytes).map_err(|e|e.to_string())?;
    if bytes.len()>2*1024*1024+64||start.elapsed().as_secs()>=5{return Err("Waveform read limit exceeded".into());}
    Ok(bytes)
}
#[tauri::command]
pub async fn dj_waveform_tile(app:AppHandle,state:State<'_,Arc<EngineSupervisor>>,session_id:String,asset_key:String,lod:u32,tile_index:u32,variant:String)->Result<tauri::ipc::Response,String>{
    if lod>25||!matches!(variant.as_str(),"full"|"bands"){return Err("Invalid waveform range".into());}
    let engine=state.inner().clone();
    let root=cache_root(&app)?;
    let bytes=tauri::async_runtime::spawn_blocking(move||read_resource(engine,session_id,root,asset_key,format!("{lod}-{tile_index}-{variant}.bin"))).await.map_err(|e|e.to_string())??;
    Ok(tauri::ipc::Response::new(bytes))
}
#[tauri::command]
pub async fn dj_waveform_manifest(app:AppHandle,state:State<'_,Arc<EngineSupervisor>>,session_id:String,asset_key:String)->Result<Value,String>{
    let engine=state.inner().clone();
    let root=cache_root(&app)?;
    let bytes=tauri::async_runtime::spawn_blocking(move||read_resource(engine,session_id,root,asset_key,"manifest.json".into())).await.map_err(|e|e.to_string())??;
    serde_json::from_slice(&bytes).map_err(|e|e.to_string())
}
#[cfg(test)] mod tests {use super::*;#[test]fn asset_keys_cannot_escape(){assert!(valid_key(&"ab".repeat(32)));for key in ["../file","",&"g".repeat(64),&"A".repeat(64)]{assert!(!valid_key(key));}}}

#[tauri::command]
pub async fn dj_waveform_pcm(app:AppHandle,state:State<'_,Arc<EngineSupervisor>>,session_id:String,asset_key:String,window_id:String)->Result<tauri::ipc::Response,String>{
    if window_id.len()>40||window_id.is_empty()||!window_id.bytes().all(|b|b.is_ascii_digit()||b==b'-'){return Err("Invalid PCM window".into());}
    let engine=state.inner().clone();
    let root=cache_root(&app)?;
    let bytes=tauri::async_runtime::spawn_blocking(move||read_resource(engine,session_id,root,asset_key,format!("pcm-{window_id}.bin"))).await.map_err(|e|e.to_string())??;
    Ok(tauri::ipc::Response::new(bytes))
}
