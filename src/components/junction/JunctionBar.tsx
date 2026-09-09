import { open as openFile, save as saveFile } from '@tauri-apps/plugin-dialog';
import type { AudioDevice } from '@/types/dj-engine';
import { junctionState } from '@/services/junction/state';
import { useEffect, useState } from 'react';
import { listen } from '@tauri-apps/api/event';
import { invoke, isTauri } from '@tauri-apps/api/core';
import { Dialog, DialogContent, DialogTitle, DialogDescription } from '@/components/ui/dialog';
import { useJunction } from '@/hooks/useJunction';
import { junctionCommand } from '@/services/junction/client';
import { djEngineClient } from '@/services/dj-engine/client';
import type { JunctionOp } from '@/types/junction';
import './junction.css';
const stages: Record<string,string> = {playing:'プレイ中',switching:'配信への反映待ち',recovery:'接続の復旧待ち',IDLE:'待機中',PREPARING:'準備中',READY:'引き継ぎ可能',FENCE:'引き継ぎを確認中',COMMITTED:'配信への反映待ち',COMPLETE:'配信へ反映済み',idle:'待機中',preparing:'準備中',ready:'引き継ぎ可能',fenced:'引き継ぎを確認中',committed:'配信への反映待ち',complete:'配信へ反映済み'};
export function JunctionBar() {
  const s = useJunction();
  const [open,setOpen] = useState(false), [busy,setBusy] = useState(false), [error,setError] = useState('');
  const [name,setName] = useState(() => localStorage.getItem('djaly.junction.name') ?? '');
  const [sessionName,setSessionName] = useState(''), [invite,setInvite] = useState('');
  const [signalingUrl,setSignalingUrl] = useState(() => localStorage.getItem('djaly.junction.signaling') ?? '');
  const [programDevice,setProgramDevice] = useState(''), [adoptCurrent,setAdopt] = useState(false);
  const [devices,setDevices] = useState<AudioDevice[]>([]);
  useEffect(() => { if (open && djEngineClient.getSessionId()) void djEngineClient.listAudioDevices().then(data => setDevices((data as {devices?:AudioDevice[]}).devices ?? [])).catch(() => {}); }, [open,s?.active]);
  const [privatePath,setPrivatePath] = useState(''), [position,setPosition] = useState(0);
  const active = Boolean(s?.active), host = active && s?.hostPeerId === s?.localPeerId;
  const peerName = (id?: string) => { const p = s?.participants.find(p => p.peerId === id); return `${p?.displayName ?? '確認中'}${id === s?.localPeerId ? '（自分）' : ''}`; };
  useEffect(() => {
    let running = false, live = true;
    const poll = async () => { if (running || !isTauri()) return; running=true; try { if ((await djEngineClient.status()).running && live) await junctionCommand('snapshot'); } catch { junctionState.unavailable(); } finally {running=false;} };
    if (isTauri()) void invoke<string | null>('junction_pending_invite').then(value => {if (value && live) {setInvite(value);setOpen(true);}});
    void poll(); const timer = setInterval(() => void poll(),1000);
    const closeListener = isTauri() ? listen('junction://close-blocked', () => {setError('終了する前に、引き継ぎ・退出またはセッション終了を完了してください。');setOpen(true);}) : Promise.resolve(() => {});
    const listener = isTauri() ? listen<string>('junction://invite', e => {setInvite(e.payload);setOpen(true);}) : Promise.resolve(() => {});
    return () => {live=false;clearInterval(timer);void listener.then(fn=>fn());void closeListener.then(fn=>fn());};
  },[]);
  const command = async (op: JunctionOp, params: Record<string,unknown> = {}) => {
    setBusy(true);setError('');
    try {localStorage.setItem('djaly.junction.name',name);localStorage.setItem('djaly.junction.signaling',signalingUrl);await junctionCommand(op,params);} catch(e) {setError(e instanceof Error ? e.message : String(e));} finally {setBusy(false);}
  };
  return <>
    <button className="junction-bar" onClick={()=>setOpen(true)} aria-label="Junction セッション設定">
      <b>Junction</b>{active && <><span>ホスト：{peerName(s?.hostPeerId)}</span><span>プレイ中：{peerName(s?.performerPeerId)}</span><span>接続：{s?.connection.state === 'stable' ? '安定' : s?.connection.state === 'connected' ? '接続済み' : '確認中'}</span><span>{s?.participants.length} 人</span></>}
    </button>
    <Dialog open={open} onOpenChange={setOpen}><DialogContent className="junction-dialog"><DialogTitle>Djaly Junction</DialogTitle><DialogDescription>同じプレイをつなぎ、次のDJへ。</DialogDescription>
      {error && <p role="alert" className="junction-error">{error}</p>}
      {!active ? <>
        <label>表示名<input value={name} onChange={e=>setName(e.target.value)} maxLength={80}/></label>
        <label>接続サーバー<input value={signalingUrl} onChange={e=>setSignalingUrl(e.target.value)} placeholder="wss://…"/></label>
        <section><h3>セッションを作成</h3><label>セッション名<input value={sessionName} onChange={e=>setSessionName(e.target.value)} maxLength={120}/></label>
          <p>手元の音・ヘッドホンCUEはプレイ画面の音声設定で確認してください。</p>
          <label>配信先デバイス<select value={programDevice} onChange={e=>setProgramDevice(e.target.value)}><option value="">配信先を選択</option>{devices.filter(d=>d.outputChannels>=2).map(d=><option key={d.id} value={/^coreaudio:\d+$/.test(d.id) ? d.id.slice(10) : d.id}>{d.name}</option>)}</select></label>
          <label className="junction-check"><input type="checkbox" checked={adoptCurrent} onChange={e=>setAdopt(e.target.checked)}/>現在の演奏をこのセッションで使う</label>
          <button disabled={busy || !name.trim() || !signalingUrl.trim()} onClick={()=>void command('create',{displayName:name,sessionName,signalingUrl,programDevice,adoptCurrent})}>作成</button>
        </section>
        <section><h3>招待を使って参加</h3><label>招待テキスト<textarea value={invite} onChange={e=>setInvite(e.target.value)} maxLength={8192}/></label><button disabled={busy || !name.trim() || !invite.trim()} onClick={()=>void command('join',{displayName:name,invite,signalingUrl})}>参加</button></section>
      </> : <>
        <p aria-live="polite">{stages[s!.handoffState] ?? '引き継ぎ状態を確認中'}{s?.readiness.reasons?.length ? ` · ${s.readiness.reasons.join('・')}` : ''}</p>
        <section><h3>参加者</h3>{s!.participants.map(p=><div className="junction-peer" key={p.peerId}><span>{peerName(p.peerId)} <small>{p.peerId.slice(0,8)}{p.peerId===s?.hostPeerId?' · ホスト':''}{p.peerId===s?.performerPeerId?' · プレイ中':''}{p.peerId===s?.nextPeerId?' · 次のDJ':''}</small></span>{host && p.approved===false && <button disabled={busy} onClick={()=>void command('peer.approve',{peerId:p.peerId})}>承認</button>}{host && p.approved!==false && p.peerId!==s?.performerPeerId && <button disabled={busy} onClick={()=>void command('handoff.request',{targetPeerId:p.peerId})}>次DJに指定</button>}</div>)}</section>
        {djEngineClient.getState().snapshot?.audio.microphone?.enabled && <button disabled={busy} onClick={()=>{setBusy(true);void djEngineClient.setMicrophone({enabled:false}).then(()=>junctionCommand("snapshot")).catch(e=>setError(e instanceof Error ? e.message : String(e))).finally(()=>setBusy(false));}}>マイクを閉じて引き継ぐ</button>}
        <div className="junction-actions"><button disabled={busy} onClick={()=>void command('handoff.request',{targetPeerId:s?.localPeerId})}>次にプレイする</button><button disabled={busy || !s?.readiness.ready || s?.nextPeerId!==s?.localPeerId} onClick={()=>void command('handoff.accept')}>操作を引き継ぐ</button><button disabled={busy || !host} onClick={()=>void command('handoff.cancel')}>引き継ぎを取消</button></div>
        {host && s?.handoffState==='recovery' && <button disabled={busy} onClick={()=>void command('recovery.resume')}>ホストの手元の演奏で配信を再開</button>}{host && <section><h3>配信先</h3><p>配信出力：{s?.program.state==='running'?'稼働中':s?.program.state==='error'?'出力エラー':'配信出力を準備中'}</p>{s?.program.localMonitor==='program-delayed' && <p>配信先とローカル出力先が同じため、メイン音は配信出力から再生します（遅延あり）。</p>}{typeof s?.program.meter==='number' && <meter aria-label="Program メーター" min={0} max={1} value={s.program.meter}/>}
          <label>出力デバイス<select value={programDevice} onChange={e=>setProgramDevice(e.target.value)}><option value="">配信先を選択</option>{devices.filter(d=>d.outputChannels>=2).map(d=><option key={d.id} value={/^coreaudio:\d+$/.test(d.id) ? d.id.slice(10) : d.id}>{d.name}</option>)}</select></label><div className="junction-actions"><button disabled={busy} onClick={()=>void command('program.configure',{programDevice})}>配信先を適用</button><button disabled={busy} onClick={()=>{ if(s?.program.recording) void command('program.record.stop'); else void saveFile({defaultPath:'Junction.wav',filters:[{name:'WAV',extensions:['wav']}]}).then(path=>{if(path) void command('program.record.start',{path});}).catch(()=>setError('保存先を選択できませんでした')); }}>{s?.program.recording?'配信録音を停止':'配信を録音'}</button><button disabled={busy} onClick={()=>void command('invite.rotate')}>招待を再発行</button><button disabled={!s?.invite} onClick={()=>void navigator.clipboard.writeText(s?.invite ?? '').catch(()=>setError('コピーできませんでした'))}>招待をコピー</button></div></section>}
        <details><summary>手元だけで試聴・次曲を準備</summary><p>共有デッキを変更せず、ヘッドホンCUEで試聴します。</p><button onClick={()=>void openFile({multiple:false,filters:[{name:"音源",extensions:["mp3","wav","flac","aiff","m4a","ogg"]}]}).then(path=>{if (typeof path === "string") setPrivatePath(path);}).catch(()=>setError("音源を選択できませんでした"))}>音源を選択</button><p>{privatePath.split(/[\\/]/).pop() || "音源が未選択です"}</p><div className="junction-actions"><button disabled={busy || !privatePath} onClick={()=>void command('private.load',{path:privatePath})}>試聴へロード</button><button disabled={busy} onClick={()=>void command('private.play')}>試聴</button><button disabled={busy} onClick={()=>void command('private.pause')}>停止</button></div><label>CUE位置（秒）<input type="number" min={0} value={position} onChange={e=>setPosition(Number(e.target.value))}/></label><button disabled={busy} onClick={()=>void command('private.seek',{positionMs:position*1000})}>位置を合わせる</button></details>
        <details><summary>接続の詳細</summary><p>{s?.connection.state} · {s?.connection.detail ?? '診断情報なし'}</p><p>引き継ぎ：{s?.handoffState}</p></details>
        <button disabled={busy} onClick={()=>void command(host?'end':'leave')}>{host?'セッションを終了':'退出'}</button>
      </>}
      {busy && <p role="status">処理中…</p>}
    </DialogContent></Dialog>
  </>;
}
