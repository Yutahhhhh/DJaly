import { useEffect, useState } from "react";
import { Loader2, Mic, RefreshCw, Volume2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { djEngineClient } from "@/services/dj-engine/client";
import { DEFAULT_MICROPHONE, savedMicrophoneSettings } from "@/services/dj-engine/audio-settings";
import type { AudioConfig, AudioDevice, MicrophoneSettings } from "@/types/dj-engine";

const selectClass = "h-8 w-full rounded border border-[#2b2d31] bg-[#0d0e0f] px-2 text-xs text-[#d8dadd] disabled:opacity-50";
const labelClass = "block text-[11px] font-semibold text-[#9b9fa6]";

export function AudioSettings({ onClose, onApply }: {
  onClose: () => void;
  onApply: (outputDevice: string, microphone?: MicrophoneSettings) => Promise<void>;
}) {
  const [devices, setDevices] = useState<AudioDevice[]>([]);
  const [selected, setSelected] = useState(() => localStorage.getItem("plumdeck.djOutputDevice") ?? "");
  const [audio, setAudio] = useState<AudioConfig | null>(null);
  const [microphone, setMicrophone] = useState<MicrophoneSettings>(() => savedMicrophoneSettings() ?? DEFAULT_MICROPHONE);
  const [loading, setLoading] = useState(true);
  const [applying, setApplying] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [revision, setRevision] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setLoading(true); setError(null);
    void (async () => {
      let status = await djEngineClient.status();
      if (!status.running) status = await djEngineClient.start();
      if (!status.running) throw new Error(status.lastError ?? status.detail ?? "音声エンジンを起動できませんでした");
      if (!djEngineClient.getSessionId()) await djEngineClient.connect();
      const result = await djEngineClient.listAudioDevices() as { devices?: AudioDevice[]; reason?: string };
      if (!Array.isArray(result.devices)) throw new Error("音声デバイス一覧を取得できませんでした");
      const config = await djEngineClient.send("audio.config.get") as AudioConfig;
      if (!cancelled) {
        setDevices(result.devices); setAudio(config);
        if (config.microphone) setMicrophone(config.microphone);
        if (result.reason) setError(result.reason);
      }
    })().catch((cause: unknown) => {
      if (!cancelled) setError(cause instanceof Error ? cause.message : String(cause));
    }).finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [revision]);

  const outputs = devices.filter(device => device.outputChannels > 0);
  const inputs = devices.filter(device => (device.inputChannels ?? 0) > 0);
  const defaultDevice = outputs.find(device => device.isDefault);
  const selectedDevice = selected ? outputs.find(device => device.name === selected) : defaultDevice;
  const ambiguous = Boolean(selected && outputs.filter(device => device.name === selected).length > 1);
  const micDevice = inputs.find(device => device.name === microphone.deviceId || device.id === microphone.deviceId);
  const micAmbiguous = inputs.filter(device => device.name === microphone.deviceId).length > 1;
  const micSupported = Boolean(audio?.microphone?.available);
  const micValid = !microphone.deviceId ? !microphone.enabled : Boolean(micDevice && !micAmbiguous && microphone.channel < (micDevice.inputChannels ?? 0));
  const canApply = Boolean(selectedDevice && selectedDevice.outputChannels >= 2 && !ambiguous && (!micSupported || micValid));
  const outputChanged = selected !== (localStorage.getItem("plumdeck.djOutputDevice") ?? "") || !audio?.applied;
  const setMic = (patch: Partial<MicrophoneSettings>) => setMicrophone(old => ({ ...old, ...patch }));
  const apply = async () => {
    setApplying(true); setError(null);
    try { await onApply(selected, micSupported ? microphone : undefined); onClose(); }
    catch (cause) { setError(cause instanceof Error ? cause.message : String(cause)); }
    finally { setApplying(false); }
  };
  const disabled = loading || applying;

  return <Dialog open onOpenChange={open => { if (!open && !applying) onClose(); }}>
    <DialogContent className="max-h-[90vh] overflow-y-auto gap-4 border-[#2b2d31] bg-[#17181a] p-4 text-[#d8dadd] sm:max-w-lg"
      onEscapeKeyDown={event => { if (applying) event.preventDefault(); }}
      onPointerDownOutside={event => { if (applying) event.preventDefault(); }}>
      <DialogHeader className="space-y-1">
        <DialogTitle className="flex items-center gap-2 text-sm font-semibold"><Volume2 className="size-4 text-[#4c83de]" />オーディオ設定</DialogTitle>
        <DialogDescription className="text-xs text-[#8b8f96]">DJの音とマイク入力をまとめてMasterへ出力します。</DialogDescription>
      </DialogHeader>
      <div className="space-y-3">
        <label className={labelClass} htmlFor="dj-output-device">マスター出力</label>
        <select id="dj-output-device" value={selected} disabled={disabled} onChange={event => setSelected(event.target.value)} className={selectClass}>
          <option value="">macOSの既定出力{defaultDevice ? ` — ${defaultDevice.displayName}` : ""}</option>
          {selected && !outputs.some(device => device.name === selected) && <option value={selected} disabled>{selected}（未接続）</option>}
          {outputs.map(device => <option key={device.id} value={device.name} disabled={device.outputChannels < 2}>{device.displayName} — {device.outputChannels} ch</option>)}
        </select>
        <p className="text-[11px] text-[#8b8f96]">{loading ? "デバイスを確認中…" : audio?.applied ? `${audio.deviceId} · ${audio.sampleRateHz.toLocaleString()} Hz · ${audio.bufferFrames} frames` : audio?.reason || "未適用"}</p>
        {selectedDevice?.name === "DDJ-1000" && <p className="text-[11px] text-[#70d9b0]">MASTER: USB 1/2 · ヘッドホンCUE: USB 3/4。本体の入力切替を接続中のUSB A/Bに合わせてください。</p>}
        {ambiguous && <p role="alert" className="text-xs text-amber-300">同名の出力が複数あります。macOSの既定出力を選択してください。</p>}
        <fieldset disabled={disabled || !micSupported} className="space-y-3 rounded border border-[#2b2d31] p-3 disabled:opacity-60">
          <legend className="flex items-center gap-1 px-1 text-xs"><Mic className="size-3.5" />マイク入力</legend>
          <label className={labelClass} htmlFor="dj-mic-device">入力デバイス</label>
          <select id="dj-mic-device" value={microphone.deviceId ?? ""} onChange={event => setMic({ deviceId: event.target.value || null, channel: 0, enabled: event.target.value ? microphone.enabled : false })} className={selectClass}>
            <option value="">使用しない</option>
            {microphone.deviceId && !micDevice && <option value={microphone.deviceId} disabled>{microphone.deviceId}（未接続）</option>}
            {inputs.map(device => <option key={device.id} value={device.name}>{device.displayName} — {device.inputChannels} ch</option>)}
          </select>
          <div className="grid grid-cols-2 items-end gap-3">
            <label className={`${labelClass} space-y-1`}><span>入力チャンネル（モノラル）</span>
              <select aria-label="マイク入力チャンネル" value={microphone.channel} disabled={!micDevice} onChange={event => setMic({ channel: Number(event.target.value) })} className={selectClass}>
                {Array.from({ length: micDevice?.inputChannels || 1 }, (_, channel) => <option key={channel} value={channel}>{channel + 1} ch</option>)}
              </select>
            </label>
            <label className="flex h-8 items-center gap-2 text-xs"><input type="checkbox" checked={microphone.enabled} disabled={!micDevice} onChange={event => setMic({ enabled: event.target.checked })} />マイクを出力する</label>
          </div>
          <label className={`${labelClass} space-y-1`}><span>マイク音量 — {Math.round(microphone.gain * 100)}%</span>
            <input aria-label="マイク音量" className="w-full accent-[#4c83de]" type="range" min={0} max={4} step={0.05} value={microphone.gain} onChange={event => setMic({ gain: Number(event.target.value) })} />
          </label>
          <label className="flex items-center gap-2 text-xs"><input type="checkbox" checked={microphone.duckingEnabled} onChange={event => setMic({ duckingEnabled: event.target.checked })} />話している間、DJの音量を自動で下げる</label>
          <label className={`${labelClass} space-y-1`}><span>DJ音量の低減量 — {Math.round(microphone.duckingStrength * 100)}%</span>
            <input aria-label="DJ音量の低減量" className="w-full accent-[#4c83de]" type="range" min={0} max={1} step={0.05} disabled={!microphone.duckingEnabled} value={microphone.duckingStrength} onChange={event => setMic({ duckingStrength: Number(event.target.value) })} />
          </label>
          <p className="text-[11px] leading-relaxed text-[#8b8f96]">マイクは左右両方へ出力され、録音にも入ります。自動調整はDJの音だけにかかります。</p>
        </fieldset>
        {!loading && !micSupported && <p className="text-xs text-amber-300">この音声エンジンはマイク入力に未対応です。更新したエンジンを起動してください。</p>}
        {micSupported && !micValid && <p role="alert" className="text-xs text-amber-300">接続済みの入力デバイスと有効なチャンネルを選択してください。同名デバイスは名前を区別してください。</p>}
        {audio?.microphone?.reason && <p className="text-xs text-amber-300">{audio.microphone.reason}</p>}
        <p className="text-[11px] leading-relaxed text-[#8b8f96]">Masterは出力1–2 chを使用します。{outputChanged ? "出力変更時は再生・録音を停止し、デッキの曲を解除します。" : "マイク音量・ON/OFF・自動調整は再生中も変更できます。入力デバイス・チャンネルの変更は録音停止後に適用してください。"}</p>
        {error && <p role="alert" className="break-words rounded border border-[#5b3835] bg-[#2e1e1d] px-2.5 py-1.5 text-xs text-[#e7a9a2]">{error}</p>}
      </div>
      <DialogFooter className="gap-2 sm:gap-2">
        <Button variant="outline" size="sm" className="mr-auto border-[#2b2d31] bg-[#212327] text-xs" disabled={disabled} onClick={() => setRevision(value => value + 1)}><RefreshCw className="size-3.5" />再取得</Button>
        <Button variant="outline" size="sm" className="border-[#2b2d31] bg-[#212327] text-xs" disabled={applying} onClick={onClose}>閉じる</Button>
        <Button size="sm" className="bg-[#315da2] text-xs" disabled={disabled || !canApply} onClick={() => void apply()}>{applying && <Loader2 className="size-3.5 animate-spin" />}適用</Button>
      </DialogFooter>
    </DialogContent>
  </Dialog>;
}
