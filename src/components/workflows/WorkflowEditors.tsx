import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import type { Track } from "@/types";
import { playService, type RecordingEntry } from "@/services/play";
import { setlistsService, type Setlist, type SetlistTrack } from "@/services/setlists";
import { workflowsService, type VersionGroup, type TimelineSegment, type AudioPreset } from "@/services/workflows";

type Runner = <T>(task: () => Promise<T>, done?: (value: T) => void) => Promise<T | undefined>;
const selectClass = "h-9 w-full rounded border bg-background px-2 text-sm";

function TrackSearch({ onSelect }: { onSelect: (track: Track) => void }) {
  const [query, setQuery] = useState("");
  const [offset, setOffset] = useState(0);
  const [rows, setRows] = useState<Track[]>([]);
  const [more, setMore] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => {
    let live = true;
    const timer = setTimeout(() => { void playService.tracksPage({ q: query, limit: 30, offset }).then(page => {
      if (live) { setRows(page.items); setMore(page.has_more); setError(""); }
    }).catch(e => { if (live) setError(String(e)); }); }, 200);
    return () => { live = false; clearTimeout(timer); };
  }, [query, offset]);
  return <div className="space-y-2"><Input aria-label="曲を検索" value={query} placeholder="曲名・アーティストで検索" onChange={e => { setQuery(e.target.value); setOffset(0); }}/>
    <div className="max-h-48 overflow-y-auto rounded border">{rows.map(track => <button key={track.id} className="block w-full border-b p-2 text-left text-sm hover:bg-muted" onClick={() => onSelect(track)}>{track.artist} — {track.title}</button>)}</div>
    {error && <p role="alert">{error}</p>}
    <div className="flex gap-2"><Button variant="outline" size="sm" disabled={!offset} onClick={() => setOffset(n => Math.max(0, n - 30))}>前へ</Button><Button variant="outline" size="sm" disabled={!more} onClick={() => setOffset(n => n + 30)}>次へ</Button></div>
  </div>;
}

export function PlaylistSelect({ value, onChange, empty = "プレイリストを選択" }: { value: string; onChange: (value: string) => void; empty?: string }) {
  const [rows, setRows] = useState<Setlist[]>([]);
  const [error, setError] = useState("");
  useEffect(() => { void setlistsService.getAll().then(setRows).catch(e => setError(String(e))); }, []);
  return <div><select aria-label="プレイリスト" className={selectClass} value={value} onChange={e => onChange(e.target.value)}><option value="">{empty}</option>{rows.map(row => <option key={row.id} value={row.id}>{row.name}</option>)}</select>{error && <p role="alert">{error}</p>}</div>;
}

export function VersionEditor({ run }: { run: Runner }) {
  const [selected, setSelected] = useState<Track[]>([]);
  const [name, setName] = useState("");
  const [group, setGroup] = useState<VersionGroup | null>(null);
  const [playlist, setPlaylist] = useState("");
  const [entries, setEntries] = useState<SetlistTrack[]>([]);
  const [entryId, setEntryId] = useState("");
  const [replacement, setReplacement] = useState("");
  const entry = entries.find(row => String(row.setlist_track_id) === entryId);
  useEffect(() => { setEntries([]); setEntryId(""); if (playlist) void run(() => setlistsService.getTracks(Number(playlist)), setEntries); }, [playlist]);
  useEffect(() => { setReplacement(""); if (entry) void run(() => workflowsService.versionsForTrack(entry.id), setGroup); }, [entry]);
  const choose = (track: Track) => { setSelected(old => old.some(t => t.id === track.id) ? old : [...old, track]); void run(() => workflowsService.versionsForTrack(track.id), setGroup); };
  return <div className="space-y-4 rounded border p-4"><h2 className="font-semibold">同じ曲の別バージョン</h2><TrackSearch onSelect={choose}/>
    <div className="flex flex-wrap gap-2">{selected.map(track => <Button key={track.id} variant="outline" size="sm" onClick={() => setSelected(old => old.filter(t => t.id !== track.id))}>{track.title} ×</Button>)}</div>
    <Input value={name} onChange={e => setName(e.target.value)} placeholder="グループ名"/>
    <Button disabled={selected.length < 2} onClick={() => void run(() => workflowsService.createVersionGroup(selected.map(t => t.id), name || undefined), setGroup)}>選択曲をグループ化</Button>
    {group && <div className="space-y-2 rounded border p-3"><h3>{group.name || "バージョングループ"}</h3>{group.members.map((member, index) => <div key={String(member.track_id)} className="flex items-center gap-2 text-sm">
      <input type="radio" aria-label={`${member.title}を優先版にする`} checked={group.preferred_track_id === Number(member.track_id)} onChange={() => setGroup({ ...group, preferred_track_id: Number(member.track_id) })}/><span className="flex-1">{String(member.title)}</span>
      <Input aria-label={`${member.title}の版名`} value={String(member.version_label ?? "")} onChange={e => setGroup({ ...group, members: group.members.map((row, i) => i === index ? { ...row, version_label: e.target.value } : row) })}/>
    </div>)}<Button onClick={() => void run(() => workflowsService.updateVersionGroup(group), setGroup)}>版名・優先版を保存</Button></div>}
    <h3 className="font-semibold">セット内の1曲を差し替える</h3><PlaylistSelect value={playlist} onChange={setPlaylist}/>
    <select aria-label="差し替える登場" className={selectClass} value={entryId} onChange={e => setEntryId(e.target.value)}><option value="">セットの曲を選択</option>{entries.map(row => <option key={row.setlist_track_id} value={row.setlist_track_id}>{row.position + 1}. {row.artist} — {row.title}</option>)}</select>
    <select aria-label="差し替え先の版" className={selectClass} value={replacement} onChange={e => setReplacement(e.target.value)}><option value="">同じグループの版を選択</option>{group?.members.filter(row => Number(row.track_id) !== entry?.id).map(row => <option key={String(row.track_id)} value={String(row.track_id)}>{String(row.title)} — {String(row.version_label)}</option>)}</select>
    <p className="text-xs text-muted-foreground">この登場だけを差し替え、IN/OUT・重なりをリセットします。</p>
    <Button disabled={!entry || !replacement} onClick={() => { if (entry) void run(async () => { await workflowsService.swapSetlistVersion(entry.setlist_track_id, Number(replacement), entry.revision); setEntries(await setlistsService.getTracks(Number(playlist))); }); }}>この登場だけ差し替え</Button>
  </div>;
}

export function RecordingEditor({ run }: { run: Runner }) {
  const [rows, setRows] = useState<RecordingEntry[]>([]);
  const [id, setId] = useState("");
  const [segments, setSegments] = useState<TimelineSegment[]>([]);
  const recording = rows.find(row => String(row.id) === id);
  const load = async () => setRows(await playService.recordings());
  useEffect(() => { void run(load); }, []);
  useEffect(() => { setSegments([]); if (id) void run(() => workflowsService.timeline(Number(id)), setSegments); }, [id]);
  const manual = segments.filter(segment => segment.source === "manual");
  const edit = (index: number, patch: Partial<TimelineSegment>) => setSegments(old => old.map((segment, i) => i === index ? { ...segment, ...patch } : segment));
  return <div className="space-y-3"><select aria-label="録音を選択" className={selectClass} value={id} onChange={e => setId(e.target.value)}><option value="">録音を選択</option>{rows.map(row => <option key={row.id} value={row.id}>{row.title || row.filepath.split("/").pop()} — {row.started_at}</option>)}</select>
    {recording && <><audio controls preload="none" src={playService.recordingAudioUrl(recording.id)} className="w-full"/><p className="text-xs text-muted-foreground">自動曲目は一定間隔の観測による推定です。細かなカットや音量変化を見落とすことがあります。手動の曲目は自動記録と分けて保存されます。</p>
      {segments.map((segment, index) => <div key={segment.id ?? `new-${index}`} className="flex items-center gap-2 rounded border p-2 text-sm"><span>{segment.source === "manual" ? "手動" : "自動推定"}</span>
        {segment.source === "manual" ? <><Input aria-label="曲名" value={segment.title_snapshot ?? ""} onChange={e => edit(index, { title_snapshot: e.target.value })}/><Input aria-label="開始秒" type="number" min={0} step={0.1} value={segment.start_ms / 1000} onChange={e => edit(index, { start_ms: Number(e.target.value) * 1000 })}/><Input aria-label="終了秒" type="number" min={0} step={0.1} value={segment.end_ms == null ? "" : segment.end_ms / 1000} onChange={e => edit(index, { end_ms: e.target.value === "" ? null : Number(e.target.value) * 1000 })}/><Button variant="outline" size="sm" onClick={() => setSegments(old => old.filter((_, i) => i !== index))}>削除</Button></> : <span>{(segment.start_ms / 1000).toFixed(1)}秒 — {segment.artist_snapshot} {segment.title_snapshot}</span>}
      </div>)}
      <Button variant="outline" onClick={() => setSegments(old => [...old, { start_ms: 0, end_ms: null, title_snapshot: "", source: "manual" }])}>手動の曲目を追加</Button>
      <Button onClick={() => void run(async () => { const value = await workflowsService.replaceTimeline(recording.id, recording.revision, manual); setSegments(value); await load(); })}>手動曲目を保存</Button>
      <a className="ml-3 underline" href={workflowsService.tracklistTextUrl(recording.id)} target="_blank" rel="noreferrer">曲目表を書き出す</a>
    </>}
  </div>;
}

export function AudioPresetSummary({ run }: { run: Runner }) {
  const [rows, setRows] = useState<AudioPreset[]>([]);
  const load = async () => setRows(await workflowsService.audioPresets());
  useEffect(() => { void run(load); }, []);
  return <div className="space-y-3 rounded border p-4"><p>プリセットの作成・適用はプレイ画面の「オーディオ設定」で、接続中の機器とMaster/CUEチャンネルを選択して行います。</p>{rows.map(row => <div key={row.id} className="flex items-center gap-2 rounded border p-2"><b className="flex-1">{row.name}</b><span className="text-sm">{String(row.config.output_device || "既定の出力")}</span><Button variant="destructive" size="sm" onClick={() => void run(async () => { await workflowsService.deleteAudioPreset(row.id); await load(); })}>削除</Button></div>)}</div>;
}
