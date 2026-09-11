import { useEffect, useRef, useState, type PointerEvent } from "react";
import { cn } from "@/lib/utils";

type Props = {
  /** 動かす CSS 変数（例 --d-tree）。ワークスペース直下に書き込む。 */
  variable: string;
  /** localStorage のキー。次回もその幅で開く。 */
  storageKey: string;
  label: string;
  min: number;
  max: number;
  /** 右側のパネルは、左へドラッグすると広がる。 */
  invert?: boolean;
};

/**
 * ブロックの境界。つまんで幅を変えられる。キーボードでも動かせるよう、
 * 分割線として役割と現在値を持たせている。
 */
export function ResizeHandle({ variable, storageKey, label, min, max, invert }: Props) {
  const [dragging, setDragging] = useState(false);
  const width = useRef(0);
  const node = useRef<HTMLDivElement>(null);
  // 幅の変数は .dj-workspace 上で定義されている。:root に書いても負けるので、
  // 実際にその変数を持っている要素へインラインで当てる。
  const scope = () => node.current?.closest<HTMLElement>("[data-resize-scope],.dj-workspace") ?? null;

  useEffect(() => {
    const stored = Number(localStorage.getItem(storageKey));
    if (Number.isFinite(stored) && stored > 0) scope()?.style.setProperty(variable, `${Math.max(min, Math.min(max, stored))}px`);
  }, [variable, storageKey]);

  const currentWidth = () => {
    const panel = invert ? node.current?.nextElementSibling : node.current?.previousElementSibling;
    const measured = panel instanceof HTMLElement ? panel.getBoundingClientRect().width : 0;
    if (measured > 0) return measured;
    const target = scope();
    const value = target ? Number.parseFloat(getComputedStyle(target).getPropertyValue(variable)) : NaN;
    return Number.isFinite(value) && value > 0 ? value : min;
  };

  const commit = (next: number) => {
    const clamped = Math.round(Math.max(min, Math.min(max, next)));
    scope()?.style.setProperty(variable, `${clamped}px`);
    localStorage.setItem(storageKey, String(clamped));
    return clamped;
  };

  const startDrag = (event: PointerEvent<HTMLDivElement>) => {
    if (event.button !== 0) return;
    event.preventDefault();
    const originX = event.clientX;
    width.current = currentWidth();
    setDragging(true);
    const move = (moveEvent: globalThis.PointerEvent) => {
      const delta = (moveEvent.clientX - originX) * (invert ? -1 : 1);
      commit(width.current + delta);
    };
    const stop = () => {
      setDragging(false);
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", stop);
      window.removeEventListener("pointercancel", stop);
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", stop);
    window.addEventListener("pointercancel", stop);
  };

  return <div
    ref={node}
    className={cn("dj-resize-handle", dragging && "is-dragging")}
    role="separator"
    aria-orientation="vertical"
    aria-label={label}
    tabIndex={0}
    onPointerDown={startDrag}
    onDoubleClick={() => { localStorage.removeItem(storageKey); scope()?.style.removeProperty(variable); }}
    onKeyDown={(event) => {
      const step = event.shiftKey ? 32 : 8;
      if (event.key === "ArrowLeft") { event.preventDefault(); commit(currentWidth() - (invert ? -step : step)); }
      if (event.key === "ArrowRight") { event.preventDefault(); commit(currentWidth() + (invert ? -step : step)); }
    }}
    title={`${label}（ドラッグで幅を調整・ダブルクリックで既定に戻す）`}
  />;
}
