import { cn } from "@/lib/utils";

export type LoopMode = "auto" | "manual";

const fraction = (beats: number) => beats >= 1 ? String(beats) : `1/${Math.round(1 / beats)}`;

type Props = {
  deckId: string;
  beats: number;
  mode: LoopMode;
  loopActive: boolean;
  hasLoop: boolean;
  disabledReason?: string;
  onMode: (mode: LoopMode) => void;
  /** 拍数を半分/倍にする。ループ中なら長さも追従させる。 */
  onBeats: (beats: number) => void;
  onSetLoop: (beats: number) => void;
  onLoopToggle: () => void;
  onLoopIn: () => void;
  onLoopOut: () => void;
};

/**
 * rekordbox デッキ中央の AUTO BEAT LOOP ブロック。
 * 上段が拍数表示、中段が ‹ › （半分 / 倍）、下段が AU / MA の切り換え。
 */
export function AutoBeatLoop(props: Props) {
  const { disabledReason: reason } = props;
  const off = Boolean(reason);
  const auto = props.mode === "auto";

  return <div className="dj-abl" role="group" aria-label={`Deck ${props.deckId} オートビートループ`}>
    {auto
      ? <button type="button" className={cn("dj-abl-value", "dj-num", props.loopActive && "is-on")} disabled={off}
          title={reason ?? "オートビートループ：指定した拍数でループが設定されます"}
          aria-pressed={props.loopActive}
          onClick={() => props.hasLoop ? props.onLoopToggle() : props.onSetLoop(props.beats)}>
          {fraction(props.beats)}
        </button>
      : <div className="dj-abl-manual">
          <button type="button" disabled={off} title={reason ?? "ループイン点を現在位置に設定"} onClick={props.onLoopIn}>IN</button>
          <button type="button" disabled={off} title={reason ?? "ループアウト点を現在位置に設定してループ開始"} onClick={props.onLoopOut}>OUT</button>
        </div>}

    <div className="dj-abl-step">
      <button type="button" disabled={off} aria-label="ループを半分の長さにする" title={reason ?? "ループを半分の長さにする"}
        onClick={() => props.onBeats(Math.max(.125, props.beats / 2))}>‹</button>
      <button type="button" disabled={off} aria-label="ループを倍の長さにする" title={reason ?? "ループを倍の長さにする"}
        onClick={() => props.onBeats(Math.min(64, props.beats * 2))}>›</button>
    </div>

    <div className="dj-abl-mode" role="group" aria-label="ループモード">
      <button type="button" className={cn(auto && "is-on")} aria-pressed={auto} disabled={off}
        title={reason ?? "オートビートループとマニュアルループを切り換えます"} onClick={() => props.onMode("auto")}>AU</button>
      <button type="button" className={cn(!auto && "is-on")} aria-pressed={!auto} disabled={off}
        title={reason ?? "オートビートループとマニュアルループを切り換えます"} onClick={() => props.onMode("manual")}>MA</button>
    </div>
  </div>;
}
