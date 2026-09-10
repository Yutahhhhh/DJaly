import { useEffect, useState } from "react";
import { open, save } from "@tauri-apps/plugin-dialog";
import { ArchiveRestore, Cable, CopyCheck, FileAudio, FolderSync, HardDrive, Layers3, Upload } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Checkbox } from "@/components/ui/checkbox";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { getErrorDetail } from "@/services/api-client";
import { workflowsService, type AudioPreset, type ControllerProfile, type ImportBatch, type RepairPlan, type UsbDevice, type UsbExport, type VersionGroup } from "@/services/workflows";
import { invoke } from "@tauri-apps/api/core";

const parseIds = (value: string) => value.split(/[\s,]+/).map(Number).filter((id) => Number.isInteger(id) && id > 0);
const pretty = (value: unknown) => JSON.stringify(value, null, 2);

export function WorkflowView() {
  const [summary, setSummary] = useState<Record<string, number>>({});
  const [status, setStatus] = useState("");
  const [busy, setBusy] = useState(false);
  const run = async <T,>(task: () => Promise<T>, done?: (value: T) => void) => {
    setBusy(true); setStatus("");
    try { const value = await task(); done?.(value); setStatus("完了しました"); return value; }
    catch (error) { setStatus(getErrorDetail(error)); }
    finally { setBusy(false); }
  };
  const refresh = () => void workflowsService.summary().then(setSummary).catch(() => undefined);
  useEffect(refresh, []);

  return <div className="h-full overflow-y-auto p-4 md:p-6">
    <div className="mx-auto max-w-6xl space-y-4">
      <div><h1 className="text-2xl font-semibold">Library Workflow Tools</h1><p className="text-sm text-muted-foreground">音源参照、版管理、完全バックアップ、機器設定、USB引き渡し、録音・外部取り込みを安全に管理します。</p></div>
      {status && <div role="status" className="rounded border bg-muted p-3 text-sm whitespace-pre-wrap">{status}</div>}
      <Tabs defaultValue="media">
        <TabsList className="h-auto flex-wrap justify-start">
          <TabsTrigger value="media">音源参照</TabsTrigger><TabsTrigger value="versions">バージョン</TabsTrigger>
          <TabsTrigger value="backup">バックアップ</TabsTrigger><TabsTrigger value="audio">音声プリセット</TabsTrigger>
          <TabsTrigger value="controller">コントローラー</TabsTrigger><TabsTrigger value="usb">USB</TabsTrigger>
          <TabsTrigger value="recordings">録音</TabsTrigger><TabsTrigger value="imports">取り込み</TabsTrigger>
        </TabsList>
        <TabsContent value="media"><MediaPanel run={run} /></TabsContent>
        <TabsContent value="versions"><VersionPanel run={run} /></TabsContent>
        <TabsContent value="backup"><BackupPanel run={run} /></TabsContent>
        <TabsContent value="audio"><AudioPresetPanel run={run} /></TabsContent>
        <TabsContent value="controller"><ControllerPanel run={run} /></TabsContent>
        <TabsContent value="usb"><UsbPanel run={run} /></TabsContent>
        <TabsContent value="recordings"><RecordingPanel run={run} /></TabsContent>
        <TabsContent value="imports"><ImportPanel run={run} /></TabsContent>
      </Tabs>
      <div className="text-xs text-muted-foreground">保存件数: {Object.entries(summary).map(([key, value]) => `${key} ${value}`).join(" / ") || "読み込み中"}</div>
      {busy && <div className="fixed inset-x-0 bottom-0 bg-primary px-4 py-1 text-center text-xs text-primary-foreground">処理中…</div>}
    </div>
  </div>;
}

type Runner = <T>(task: () => Promise<T>, done?: (value: T) => void) => Promise<T | undefined>;
const Shell = ({ icon, title, description, children }: { icon: React.ReactNode; title: string; description: string; children: React.ReactNode }) => <Card><CardHeader><CardTitle className="flex items-center gap-2">{icon}{title}</CardTitle><CardDescription>{description}</CardDescription></CardHeader><CardContent className="space-y-3">{children}</CardContent></Card>;

function MediaPanel({ run }: { run: Runner }) {
  const [ids, setIds] = useState(""); const [oldRoot, setOldRoot] = useState(""); const [newRoot, setNewRoot] = useState(""); const [plan, setPlan] = useState<RepairPlan | null>(null); const [choices, setChoices] = useState<Record<string, string>>({});
  return <Shell icon={<FolderSync />} title="音源参照の診断と修復" description="まず診断し、候補を確認してから参照だけを更新します。曲ID・解析・履歴は維持されます。">
    <div className="grid gap-2 md:grid-cols-3"><Input value={ids} onChange={(e) => setIds(e.target.value)} placeholder="曲ID（空欄で全曲）"/><Input value={oldRoot} onChange={(e) => setOldRoot(e.target.value)} placeholder="以前のルート /Volumes/old"/><Input value={newRoot} onChange={(e) => setNewRoot(e.target.value)} placeholder="新しいルート /Volumes/new"/></div>
    <Button onClick={() => void run(() => workflowsService.diagnoseMedia({ track_ids: parseIds(ids).length ? parseIds(ids) : undefined, old_root: oldRoot || undefined, new_root: newRoot || undefined }), setPlan)}>診断する</Button>
    {plan?.items.map((item) => <div key={item.track_id} className="rounded border p-3 text-sm"><div className="flex justify-between"><b>#{item.track_id} {item.artist} — {item.title}</b><span>{item.access_state}</span></div><div className="truncate text-muted-foreground">{item.old_path}</div>{item.access_state === "missing" && <Input className="mt-2" value={choices[String(item.track_id)] ?? item.candidate_path ?? ""} onChange={(e) => setChoices((old) => ({...old, [item.track_id]: e.target.value}))} placeholder="確認済みの新しい絶対パス"/>}</div>)}
    {plan && <div className="flex gap-2"><Button onClick={() => void run(() => workflowsService.applyRepair(plan.id, choices), () => setPlan(null))}>選択した参照を更新</Button><Button variant="outline" onClick={() => void run(() => workflowsService.undoRepair(plan.id))}>直前の更新を戻す</Button></div>}
  </Shell>;
}

function VersionPanel({ run }: { run: Runner }) {
  const [ids, setIds] = useState(""); const [name, setName] = useState(""); const [lookup, setLookup] = useState(""); const [group, setGroup] = useState<VersionGroup | null>(null); const [entry, setEntry] = useState(""); const [replacement, setReplacement] = useState(""); const [entryRevision, setEntryRevision] = useState("1");
  return <Shell icon={<Layers3 />} title="同じ曲の別バージョン" description="Original / Clean / Intro / Extendedなどを1グループにまとめます。音源ファイル自体は変更しません。">
    <div className="flex gap-2"><Input value={name} onChange={(e) => setName(e.target.value)} placeholder="グループ名（任意）"/><Input value={ids} onChange={(e) => setIds(e.target.value)} placeholder="曲IDを2件以上: 12, 34"/><Button onClick={() => void run(() => workflowsService.createVersionGroup(parseIds(ids), name || undefined), setGroup)}>作成</Button></div>
    <div className="flex gap-2"><Input value={lookup} onChange={(e) => setLookup(e.target.value)} placeholder="曲IDからグループを表示"/><Button variant="outline" onClick={() => void run(() => workflowsService.versionsForTrack(Number(lookup)), (value) => setGroup(value))}>検索</Button></div>
    {group && <pre className="max-h-96 overflow-auto rounded bg-muted p-3 text-xs">{pretty(group)}</pre>}
    <div className="border-t pt-3"><p className="mb-2 text-xs text-muted-foreground">セット内の指定した登場だけを別版へ差し替えます。</p><div className="grid gap-2 md:grid-cols-4"><Input value={entry} onChange={(e) => setEntry(e.target.value)} placeholder="setlist entry ID"/><Input value={replacement} onChange={(e) => setReplacement(e.target.value)} placeholder="差替先の曲ID"/><Input value={entryRevision} onChange={(e) => setEntryRevision(e.target.value)} placeholder="entry revision"/><Button onClick={() => void run(() => workflowsService.swapSetlistVersion(Number(entry), Number(replacement), Number(entryRevision)))}>この登場だけ差替</Button></div></div>
  </Shell>;
}

function BackupPanel({ run }: { run: Runner }) {
  const [media, setMedia] = useState(false); const [recordings, setRecordings] = useState(false); const [restorePath, setRestorePath] = useState(""); const [inspection, setInspection] = useState<Record<string, unknown> | null>(null);
  const create = async () => { const selected = await save({ title: "完全バックアップを保存", defaultPath: "plumdeck.plumdeck-backup", filters: [{ name: "plumdeck backup", extensions: ["plumdeck-backup"] }] }); if (selected) await run(() => workflowsService.createBackup(selected, media, recordings)); };
  const choose = async () => { const selected = await open({ multiple: false, filters: [{ name: "plumdeck backup", extensions: ["plumdeck-backup"] }] }); if (typeof selected === "string") { setRestorePath(selected); await run(() => workflowsService.inspectBackup(selected), setInspection); } };
  return <Shell icon={<ArchiveRestore />} title="完全バックアップと復元" description="DB、解析ジョブ、UI設定をmanifestとSHA-256付きで保存します。必要に応じて音源・録音も含められます。">
    <label className="flex items-center gap-2"><Checkbox checked={media} onCheckedChange={(v) => setMedia(v === true)}/>音源を含める</label><label className="flex items-center gap-2"><Checkbox checked={recordings} onCheckedChange={(v) => setRecordings(v === true)}/>録音を含める</label>
    <div className="flex gap-2"><Button onClick={() => void create()}>バックアップを作成</Button><Button variant="outline" onClick={() => void choose()}>復元ファイルを検査</Button></div>
    {inspection && <><pre className="max-h-64 overflow-auto rounded bg-muted p-3 text-xs">{pretty(inspection)}</pre><Button variant="destructive" onClick={() => { if (confirm("現在のplumdeckデータを置き換えます。続けますか？")) void run(() => workflowsService.restoreBackup(restorePath), (result) => { Object.keys(localStorage).filter((key) => key === "vite-ui-theme" || key.startsWith("plumdeck.")).forEach((key) => localStorage.removeItem(key)); Object.entries(result.ui_settings).forEach(([key,value]) => localStorage.setItem(key,value)); window.location.reload(); }); }}>検査済みバックアップへ復元</Button></>}
  </Shell>;
}

function AudioPresetPanel({ run }: { run: Runner }) {
  const [rows, setRows] = useState<AudioPreset[]>([]); const [name, setName] = useState(""); const [config, setConfig] = useState('{"output_device":"","master":{"device_id":"default","channels":[0,1]},"cue":null,"buffer_size":256,"sample_rate":44100}');
  const load = () => void workflowsService.audioPresets().then(setRows); useEffect(load, []);
  return <Shell icon={<FileAudio />} title="音声ルーティングプリセット" description="Master/CueのデバイスIDとチャンネル、サンプルレート、バッファーを名前付きで保存します。適用前の再確認にも使えます。">
    <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="プリセット名"/><textarea className="min-h-32 w-full rounded border bg-background p-2 font-mono text-xs" value={config} onChange={(e) => setConfig(e.target.value)}/><Button onClick={() => void run(() => workflowsService.saveAudioPreset(name, JSON.parse(config)), load)}>保存</Button>
    {rows.map((row) => <div key={row.id} className="flex items-center gap-2 rounded border p-2 text-sm"><b className="flex-1">{row.name}</b><Button size="sm" variant="outline" onClick={() => setConfig(JSON.stringify(row.config, null, 2))}>読み込む</Button><Button size="sm" variant="destructive" onClick={() => void run(() => workflowsService.deleteAudioPreset(row.id), load)}>削除</Button></div>)}
  </Shell>;
}

function ControllerPanel({ run }: { run: Runner }) {
  const [rows, setRows] = useState<ControllerProfile[]>([]); const [json, setJson] = useState(""); const [devices, setDevices] = useState<string[]>([]); const [device, setDevice] = useState(() => localStorage.getItem("plumdeck.midi.device") ?? ""); const [learnAction, setLearnAction] = useState("deck.play"); const [learnDeck, setLearnDeck] = useState("A"); const load = () => void workflowsService.controllerProfiles().then(setRows); useEffect(() => { load(); void invoke<{inputs:string[]}>("dj_midi_devices").then((value) => setDevices(value.inputs)).catch(() => undefined); }, []);
  const readFile = async (file?: File) => { if (file) setJson(await file.text()); };
  const exportProfile = (row: ControllerProfile) => { const blob = new Blob([JSON.stringify(row, null, 2)], {type:"application/json"}); const a = document.createElement("a"); a.href = URL.createObjectURL(blob); a.download = `${row.name}.json`; a.click(); URL.revokeObjectURL(a.href); };
  const activate = (row: ControllerProfile) => { localStorage.setItem("plumdeck.midi.profile", JSON.stringify(row)); localStorage.setItem("plumdeck.midi.device", device); void invoke("dj_midi_select_device", {device: device || null}); };
  const learn = async () => {
    if (!device) throw new Error("MIDI Learnでは入力機器を選択してください");
    await invoke("dj_midi_select_device", {device});
    const deadline = Date.now() + 10_000;
    try {
      while (Date.now() < deadline) {
        await invoke("dj_midi_status", {enabled:true});
        const events = await invoke<Array<{messages:number[][]}>>("dj_midi_read");
        const message = events.flatMap((event) => event.messages).find((bytes) => bytes.length >= 3);
        if (message) {
          const status = message[0] & 0xf0; const channel = message[0] & 0x0f;
          const kind = status === 0xb0 ? "cc" : status === 0xe0 ? "pitchbend" : status === 0x90 || status === 0x80 ? "note" : null;
          if (!kind) continue;
          const profile = (() => { try { return JSON.parse(json); } catch { return {schemaVersion:1,adapterId:"generic-midi",name:`${device} mapping`,bindings:[]}; } })();
          profile.schemaVersion = 1; profile.adapterId = "generic-midi"; profile.name ||= `${device} mapping`; profile.bindings ||= [];
          profile.bindings.push({id:crypto.randomUUID(),input:{kind,channel,number:kind === "pitchbend" ? 0 : message[1]},encoding:kind === "note" ? "button" : "absolute",actionId:learnAction,deck:learnAction === "mixer.crossfader" || learnAction.startsWith("library.") ? undefined : learnDeck,trigger:kind === "note" ? "hold" : undefined});
          setJson(pretty(profile)); return profile;
        }
        await new Promise((resolve) => setTimeout(resolve, 100));
      }
      throw new Error("10秒以内にMIDI入力を受信できませんでした");
    } finally { await invoke("dj_midi_status", {enabled:false}).catch(() => undefined); }
  };
  return <Shell icon={<Cable />} title="DJコントローラープロファイル" description="DDJ-400の内蔵マッピングと、MIDI Learnで作った汎用JSONマッピングを検証・保存します。競合する入力は保存時に拒否されます。">
    <select className="h-9 w-full rounded border bg-background px-2 text-sm" value={device} onChange={(e) => setDevice(e.target.value)}><option value="">DDJ-1000 / DDJ-400を自動検出</option>{devices.map((name) => <option key={name} value={name}>{name}</option>)}</select>
    <div className="grid gap-2 md:grid-cols-3"><select className="h-9 rounded border bg-background px-2 text-sm" value={learnAction} onChange={(e) => setLearnAction(e.target.value)}>{["deck.play","deck.cue","deck.sync","deck.tempo","deck.jog","deck.jog_touch","mixer.trim","mixer.eq_low","mixer.eq_mid","mixer.eq_high","mixer.channel_fader","mixer.crossfader","mixer.filter","mixer.cue","library.browse","library.load","loop.in","loop.out","loop.exit","loop.size"].map((id) => <option key={id}>{id}</option>)}</select><select className="h-9 rounded border bg-background px-2 text-sm" value={learnDeck} onChange={(e) => setLearnDeck(e.target.value)}>{["A","B","C","D"].map((id) => <option key={id}>{id}</option>)}</select><Button variant="outline" onClick={() => void run(learn)}>MIDI Learn（10秒）</Button></div>
    <input type="file" accept="application/json,.json" onChange={(e) => void readFile(e.target.files?.[0])}/><textarea className="min-h-40 w-full rounded border bg-background p-2 font-mono text-xs" value={json} onChange={(e) => setJson(e.target.value)} placeholder='{"schemaVersion":1,"adapterId":"generic-midi","name":"My MIDI","bindings":[...]}'/><Button onClick={() => void run(() => workflowsService.saveControllerProfile(JSON.parse(json)), load)}>JSONを検証して保存</Button>
    {rows.map((row) => <div key={row.id} className="flex items-center gap-2 rounded border p-2 text-sm"><b className="flex-1">{row.name}</b><span>{row.id.startsWith("builtin-") ? "内蔵" : "カスタム"}</span><Button size="sm" onClick={() => activate(row)}>この機器で使用</Button><Button size="sm" variant="outline" onClick={() => exportProfile(row)}>書き出し</Button></div>)}
  </Shell>;
}

function UsbPanel({ run }: { run: Runner }) {
  const [setlistId, setSetlistId] = useState(""); const [rows, setRows] = useState<UsbExport[]>([]); const [devices, setDevices] = useState<UsbDevice[]>([]); const load = () => { void workflowsService.usbHandoffs().then(setRows); void workflowsService.usbDevices().then(setDevices); }; useEffect(load, []);
  return <Shell icon={<HardDrive />} title="Rekordbox経由USB引き渡し" description="セットリストを固定スナップショット化し、Rekordbox XMLとmanifestを生成します。plumdeckが直接Pioneer USBデータベースを書くことはありません。">
    <div className="flex gap-2"><Input value={setlistId} onChange={(e) => setSetlistId(e.target.value)} placeholder="セットリストID"/><Button onClick={() => void run(() => workflowsService.createUsbHandoff(Number(setlistId)), load)}>引き渡しを作成</Button></div>
    <div className="space-y-2">{devices.map((device) => <div key={device.id} className="flex items-center gap-2 rounded border p-2 text-sm"><HardDrive className="size-4"/><b className="flex-1">{device.label}</b><span>{device.filesystem} · {device.read_only ? "読取専用" : "書込可"}</span><Button size="sm" variant="outline" onClick={() => void run(() => workflowsService.ejectUsb(device.id), load)}>安全に取り外す</Button></div>)}<Button size="sm" variant="ghost" onClick={load}>USBを再検出</Button></div>
    {rows.map((row) => <div key={row.id} className="rounded border p-3 text-sm"><div className="flex gap-2"><b className="flex-1">Setlist #{row.setlist_id}</b><span>{row.state}</span></div>{row.stale && <p className="text-destructive">作成後にセットまたは音源が変わりました。更新版を新規作成してください。</p>}<div className="select-text break-all text-xs text-muted-foreground">{row.handoff_path}</div><div className="mt-2 flex flex-wrap gap-2"><Button size="sm" variant="outline" onClick={() => void run(() => workflowsService.verifyUsbHandoff(row.id, { level: "user_rekordbox_check", checked_at: new Date().toISOString(), checks: ["rekordboxでプレイリスト・曲順・CUE・gridを確認"] }), load)}>Rekordbox確認を記録</Button><Button size="sm" variant="outline" onClick={() => void run(() => workflowsService.duplicateUsbHandoff(row.id), load)}>同じsnapshotを予備USBへ</Button></div></div>)}
  </Shell>;
}

function RecordingPanel({ run }: { run: Runner }) {
  const [id, setId] = useState(""); const [revision, setRevision] = useState("1"); const [segments, setSegments] = useState("[]"); const [path, setPath] = useState(""); const [title, setTitle] = useState("");
  const choose = async () => { const selected = await open({multiple:false, filters:[{name:"Audio",extensions:["wav","wave","flac","aif","aiff","mp3","ogg","oga"]}]}); if(typeof selected === "string") setPath(selected); };
  return <Shell icon={<CopyCheck />} title="録音タイムライン" description="録音に曲目、版、開始・終了時刻を付け、テキスト曲目表にできます。外部録音も登録できます。">
    <div className="flex gap-2"><Input value={id} onChange={(e) => setId(e.target.value)} placeholder="録音ID"/><Input value={revision} onChange={(e) => setRevision(e.target.value)} placeholder="revision"/><Button variant="outline" onClick={() => void run(() => workflowsService.timeline(Number(id)), (value) => setSegments(pretty(value)))}>読込</Button><a className="inline-flex items-center rounded border px-3 text-sm" href={workflowsService.tracklistTextUrl(Number(id))} target="_blank">曲目表</a></div>
    <textarea className="min-h-48 w-full rounded border bg-background p-2 font-mono text-xs" value={segments} onChange={(e) => setSegments(e.target.value)}/><Button onClick={() => void run(() => workflowsService.replaceTimeline(Number(id), Number(revision), JSON.parse(segments)))}>手動タイムラインを保存</Button>
    <div className="border-t pt-3"><div className="grid gap-2 md:grid-cols-2"><Input value={path} onChange={(e) => setPath(e.target.value)} placeholder="外部録音ファイル"/><Input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="タイトル"/></div><p className="mt-2 text-xs text-muted-foreground">長さは音声ファイルから検証して登録します。</p><div className="mt-2 flex gap-2"><Button variant="outline" onClick={() => void choose()}>ファイルを選択</Button><Button onClick={() => void run(() => workflowsService.registerExternalRecording({filepath:path,title,artist:""}))}>外部録音を登録</Button></div></div>
  </Shell>;
}

function ImportPanel({ run }: { run: Runner }) {
  const [paths, setPaths] = useState<string[]>([]); const [playlist, setPlaylist] = useState(""); const [rows, setRows] = useState<ImportBatch[]>([]); const load = () => void workflowsService.imports().then(setRows); useEffect(load, []);
  const choose = async () => { const selected = await open({multiple:true, directory:false, filters:[{name:"Audio",extensions:["mp3","wav","flac","aiff","m4a","ogg"]}]}); setPaths(typeof selected === "string" ? [selected] : selected ?? []); };
  return <Shell icon={<Upload />} title="Play中の安全な音源取り込み" description="音源またはフォルダをCollection / plumdeckプレイリストへ取り込みます。元ファイルは変更せず、重複はパスとSHA-256で判定します。">
    <div className="flex gap-2"><Button variant="outline" onClick={() => void choose()}>音源を選択</Button><Input value={playlist} onChange={(e) => setPlaylist(e.target.value)} placeholder="追加先プレイリストID（空欄=Collection）"/><Button disabled={!paths.length} onClick={() => void run(() => workflowsService.createImport(paths, playlist ? {kind:"local_playlist",id:Number(playlist)} : {kind:"collection"}), load)}>取り込み開始</Button></div><div className="text-xs text-muted-foreground">{paths.length ? `${paths.length}件を選択` : "未選択"}</div>
    {rows.map((row) => <div key={row.id} className="rounded border p-2 text-sm"><div className="flex gap-2"><b className="flex-1">{row.id}</b><span>{row.state}</span></div><div>{row.succeeded_items}/{row.total_items} 成功 · {row.failed_items} 失敗 · {row.skipped_items} スキップ</div>{["failed","completed_with_errors","canceled","paused"].includes(row.state) && <Button size="sm" variant="outline" onClick={() => void run(() => workflowsService.controlImport(row.id, row.state === "paused" ? "resume" : "retry"), load)}>再開/再試行</Button>}</div>)}
  </Shell>;
}
