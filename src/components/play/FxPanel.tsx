import { cn } from "@/lib/utils";
import { PAD_EFFECTS, type DeckId, type PadEffect } from "@/types/dj-engine";
import { RotaryKnob } from "./RotaryKnob";

/** rekordbox の表記に寄せたラベル。値は Mixxx の内蔵エフェクト名。 */
const FX_LABELS: Record<PadEffect, string> = {
  echo: "ECHO", reverb: "REVERB", flanger: "FLANGER", phaser: "PHASER", filter: "FILTER",
  bitcrusher: "CRUSH", distortion: "DISTORTION", autopan: "PAN", tremolo: "TREMOLO",
  moogladder4filter: "MOOG FILTER",
};

export type FxUnitState = { channel: DeckId; effect: PadEffect; mix: number; enabled: boolean };

export const FX_UNIT_DEFAULTS: [FxUnitState, FxUnitState] = [
  { channel: "A", effect: "echo", mix: .8, enabled: false },
  { channel: "B", effect: "flanger", mix: .8, enabled: false },
];

type Props = {
  decks: readonly DeckId[];
  units: [FxUnitState, FxUnitState];
  /** 未接続などで触れない理由。undefined なら操作可。 */
  disabledReason?: string;
  onChange: (index: 0 | 1, unit: FxUnitState) => void;
};

/**
 * rekordbox の FX パネル。実機は 1 ユニットに 3 スロット＋リリース FX を持つが、
 * この音声エンジンの `mixer.fx.set` は 1 チャンネル 1 エフェクトなので、
 * 効く操作だけを出す。動かない枠を並べても混乱するだけなので置かない。
 */
export function FxPanel({ decks, units, disabledReason, onChange }: Props) {
  return <section className="dj-fx-panel" aria-label="エフェクトパネル">
    {units.map((unit, index) => <FxUnit key={index} index={index as 0 | 1} unit={unit} decks={decks}
      disabledReason={disabledReason} onChange={onChange} />)}
  </section>;
}

function FxUnit({ index, unit, decks, disabledReason, onChange }: {
  index: 0 | 1; unit: FxUnitState; decks: readonly DeckId[]; disabledReason?: string;
  onChange: (index: 0 | 1, unit: FxUnitState) => void;
}) {
  const off = Boolean(disabledReason);
  const set = (patch: Partial<FxUnitState>) => onChange(index, { ...unit, ...patch });

  return <div className="dj-fx-unit" aria-label={`FX${index + 1}`}>
    <span className="dj-fx-label">FX{index + 1}</span>

    <div className="dj-fx-assign" role="group" aria-label={`FX${index + 1} 適用チャンネル`}>
      {decks.map((deck) => <button key={deck} type="button" className={cn(unit.channel === deck && "is-on")}
        disabled={off} aria-pressed={unit.channel === deck} title={disabledReason ?? `Deck ${deck} に適用`}
        onClick={() => set({ channel: deck })}>{deck}</button>)}
    </div>

    <div className="dj-fx-slot">
      <select aria-label={`FX${index + 1} エフェクト`} value={unit.effect} disabled={off}
        onChange={(event) => set({ effect: event.target.value as PadEffect })}>
        {PAD_EFFECTS.map((effect) => <option key={effect} value={effect}>{FX_LABELS[effect]}</option>)}
      </select>
      <RotaryKnob label="DEPTH" min={0} max={1} step={.02} fineStep={.005} defaultValue={.8} value={unit.mix}
        disabled={off} valueText={(value) => `${Math.round(value * 100)}%`} onChange={(value) => set({ mix: value })} />
    </div>

    <div className="dj-fx-onoff">
      <button type="button" className={cn("dj-fx-auto", unit.enabled && "is-on")} disabled={off} aria-pressed={unit.enabled}
        title={disabledReason ?? "エフェクトのオン/オフ"} onClick={() => set({ enabled: !unit.enabled })}>ON</button>
    </div>
  </div>;
}
