//! Bounded local channel independent of WebView rendering and notification ACKs.
use serde::{Deserialize,Serialize};
use serde_json::{json,Value};
use std::{io::{Read,Write},os::unix::net::UnixStream,time::{Duration,Instant}};
#[derive(Clone,Debug,Deserialize,PartialEq)]
#[serde(rename_all="camelCase")]
pub struct Config {pub path:String,pub token:String,pub sensitivity:f64,pub ranges:[f64;4],pub cues:[f64;4]}
#[derive(Clone,Debug,Default,Serialize)]
#[serde(rename_all="camelCase")]
pub struct Observation {pub active:bool,pub cues:[f64;4],pub ranges:[f64;4]}
pub struct Transport {stream:UnixStream,input:Vec<u8>,generations:[u32;4],origin:Instant,offset:f64,seq:u64,last_write:Instant,pub observation:Observation}
impl Transport {
 pub fn connect(config:&Config)->Result<Self,String>{
  if !config.sensitivity.is_finite()||config.sensitivity<=0.0||config.sensitivity>20.0||config.ranges.iter().chain(config.cues.iter()).any(|v|!v.is_finite()){return Err("Invalid performance settings".into());}
  let mut stream=UnixStream::connect(&config.path).map_err(|e|e.to_string())?;
  stream.set_read_timeout(Some(Duration::from_millis(200))).map_err(|e|e.to_string())?;
  stream.set_write_timeout(Some(Duration::from_millis(20))).map_err(|e|e.to_string())?;
  let origin=Instant::now();let mut hello=serde_json::to_vec(&json!({"token":config.token,"sensitivity":config.sensitivity,"ranges":config.ranges,"cues":config.cues})).unwrap();hello.push(b'\n');stream.write_all(&hello).map_err(|e|e.to_string())?;
  let mut input=Vec::new();let mut byte=[0];while input.len()<16384 {stream.read_exact(&mut byte).map_err(|e|e.to_string())?;if byte[0]==b'\n'{break;}input.push(byte[0]);}
  let state:Value=serde_json::from_slice(&input).map_err(|e|e.to_string())?;
  let offset=state["nativeUs"].as_f64().ok_or("Missing native clock")?-origin.elapsed().as_secs_f64()*500000.0;
  stream.set_nonblocking(true).map_err(|e|e.to_string())?;
  let mut transport=Self{stream,input:Vec::new(),generations:[0;4],origin,offset,seq:0,last_write:Instant::now(),observation:Observation{active:true,cues:config.cues,ranges:config.ranges}};
  transport.observe(&state);Ok(transport)
 }
 fn observe(&mut self,value:&Value){for i in 0..4 {if let Some(g)=value["decks"][i]["generation"].as_u64(){self.generations[i]=g as u32;}if let Some(c)=value["decks"][i]["cueMs"].as_f64(){self.observation.cues[i]=c;}if let Some(r)=value["decks"][i]["range"].as_f64(){self.observation.ranges[i]=r;}}}
 pub fn poll(&mut self)->Result<(),String>{
  let mut bytes=[0;4096];loop{match self.stream.read(&mut bytes){Ok(0)=>return Err("Native input disconnected".into()),Ok(n)=>{self.input.extend_from_slice(&bytes[..n]);if self.input.len()>16384{return Err("Native observation overflow".into());}},Err(e) if e.kind()==std::io::ErrorKind::WouldBlock=>break,Err(e)=>return Err(e.to_string())}}
  while let Some(end)=self.input.iter().position(|&b|b==b'\n'){let value:Value=serde_json::from_slice(&self.input[..end]).map_err(|e|e.to_string())?;self.observe(&value);self.input.drain(..=end);}
  if self.last_write.elapsed()>Duration::from_millis(200){self.send(&[],Instant::now())?;}Ok(())
 }
 pub fn send(&mut self,bytes:&[u8],captured:Instant)->Result<(),String>{
  // Long SysEx belongs to the display path. Channel messages and running
  // status are streamed in at most three-byte fragments without allocation.
  if bytes.first()==Some(&0xf0){return Ok(());}
  let fragments=if bytes.is_empty(){1}else{bytes.len().div_ceil(3)};
  if fragments>64{return Err("Native input batch too large".into());}
  let mut buffer=[0u8;48*64];
  for fragment in 0..fragments {
   self.seq+=1;let row=&mut buffer[fragment*48..(fragment+1)*48];row[..8].copy_from_slice(&self.seq.to_le_bytes());
   let elapsed=if captured>=self.origin{captured.duration_since(self.origin).as_secs_f64()}else{-self.origin.duration_since(captured).as_secs_f64()};
   let native=(self.offset+elapsed*1e6).max(0.0) as u64;row[8..16].copy_from_slice(&native.to_le_bytes());
   for i in 0..4{row[16+i*4..20+i*4].copy_from_slice(&self.generations[i].to_le_bytes());}
   let first=fragment*3;let n=bytes.len().saturating_sub(first).min(3);row[32]=n as u8;if n>0{row[33..33+n].copy_from_slice(&bytes[first..first+n]);}
  }
  // Nonblocking writes never wait behind the WebView. Any partial write
  // invalidates the connection; its drop aborts native gestures.
  match self.stream.write(&buffer[..fragments*48]){Ok(n) if n==fragments*48=>{self.last_write=Instant::now();Ok(())},Ok(_)=>Err("Native input overflow".into()),Err(e)=>Err(e.to_string())}
 }
}
