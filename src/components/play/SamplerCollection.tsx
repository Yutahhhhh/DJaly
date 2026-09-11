import { useState, useSyncExternalStore } from "react";
import { open } from "@tauri-apps/plugin-dialog";
import { samplerLibrary, SAMPLE_MIME, sampleDrag } from "@/services/sampler-library";

const TRACK_MIME = "application/x-plumdeck-track";

export function SamplerCollection() {
  const assets = useSyncExternalStore(samplerLibrary.subscribe, samplerLibrary.snapshot);
  const [query, setQuery] = useState("");
  const [error, setError] = useState("");
  const choose = async () => {
    setError("");
    try {
      const paths = await open({ multiple: true, filters: [{ name: "Audio", extensions: ["wav", "aif", "aiff", "mp3", "flac", "m4a", "ogg", "opus"] }] });
      if (paths) samplerLibrary.add(typeof paths === "string" ? [paths] : paths);
    } catch (cause) { setError(String(cause)); }
  };
  const [dropActive, setDropActive] = useState(false);
  const dropTrack = (event: React.DragEvent) => {
    event.preventDefault(); setDropActive(false); setError("");
    try {
      const track = JSON.parse(event.dataTransfer.getData(TRACK_MIME)) as { filepath?: string };
      if (!track.filepath) throw new Error("音源ファイルの場所が分からない曲は登録できません。");
      samplerLibrary.add([track.filepath]);
    } catch (cause) { setError(cause instanceof Error ? cause.message : String(cause)); }
  };
  return <section data-sampler-collection data-native-drop-active={dropActive ? "true" : undefined} className="sampler-collection"
    onDragOver={event => { if (event.dataTransfer.types.includes(TRACK_MIME)) { event.preventDefault(); event.dataTransfer.dropEffect = "copy"; setDropActive(true); } }}
    onDragLeave={() => setDropActive(false)}
    onDrop={event => { if (event.dataTransfer.types.includes(TRACK_MIME)) dropTrack(event); }}>
    <div className="sampler-collection-tools"><input aria-label="サンプラー音源を検索" placeholder="音源を検索…" value={query} onChange={event => setQuery(event.target.value)} /><button onClick={() => void choose()}>音源を登録</button><span>{assets.length}音源</span></div>
    <p className="sampler-collection-hint">ライブラリの曲や音源ファイルをここへドロップして登録。音源をSAMPLERのPADへドラッグして割り当てます。解析は行いません。</p>
    <p className="sampler-collection-hint">元ファイルを参照します。移動・削除すると再登録が必要です。一覧からの削除では元ファイルやPADの割当は消えません。</p>
    {error && <p role="alert">{error}</p>}
    <div className="sampler-collection-list">{assets.filter(asset => asset.name.toLowerCase().includes(query.toLowerCase())).map(asset => <div key={asset.path} className="sampler-collection-row" draggable
      onDragStart={event => { event.dataTransfer.setData(SAMPLE_MIME, JSON.stringify(asset)); event.dataTransfer.effectAllowed = "copy"; sampleDrag.start(asset); }} onDragEnd={() => sampleDrag.end()}>
      <span title={asset.path}>{asset.name}</span><button aria-label={`${asset.name}を登録解除`} onClick={() => { try { samplerLibrary.remove(asset.path); } catch (cause) { setError(String(cause)); } }}>×</button>
    </div>)}{!assets.length && <div className="sampler-collection-empty">曲や音源ファイルをここにドロップ</div>}</div>
  </section>;
}
