import { Channel, invoke, isTauri } from "@tauri-apps/api/core";

/**
 * Outbound drag of an original audio file, so a candidate can be dropped
 * straight onto a rekordbox deck.
 *
 * The file itself is never copied, converted or re-exported: the OS drag
 * carries the path plumdeck already has, and rekordbox loads that same original.
 * An HTML drag only ever carries `application/x-plumdeck-track`, which nothing
 * outside this window understands, so the native session is what makes the drop
 * work at all.
 */

export type DragResult = "Dropped" | "Cancel";

interface DragCallback {
  result: DragResult;
  cursorPos: { x: number; y: number };
}

export interface DragOutcome {
  started: boolean;
  result?: DragResult;
  message?: string;
}

/** A small label the OS shows under the cursor while dragging. */
function dragImage(label: string): string {
  const width = 240;
  const height = 34;
  const canvas = document.createElement("canvas");
  const ratio = Math.min(window.devicePixelRatio || 1, 2);
  canvas.width = width * ratio;
  canvas.height = height * ratio;
  const context = canvas.getContext("2d");
  if (!context) return "";
  context.scale(ratio, ratio);
  context.fillStyle = "rgba(15, 23, 42, 0.94)";
  context.fillRect(0, 0, width, height);
  context.strokeStyle = "rgba(251, 191, 36, 0.9)";
  context.strokeRect(0.5, 0.5, width - 1, height - 1);
  context.fillStyle = "#fbbf24";
  context.font = "13px -apple-system, system-ui, sans-serif";
  context.textBaseline = "middle";
  const text = label.length > 30 ? `${label.slice(0, 29)}…` : label;
  context.fillText(text, 10, height / 2);
  return canvas.toDataURL("image/png");
}

export function canDragOut(): boolean {
  return isTauri();
}

/**
 * Starts the native drag. Resolves once the OS drag session finishes so the
 * caller can keep the candidate list frozen for exactly that long.
 */
export async function startFileDrag(filepath: string, label: string): Promise<DragOutcome> {
  if (!canDragOut()) {
    return {
      started: false,
      message: "ドラッグ＆ドロップはデスクトップアプリでのみ利用できます",
    };
  }
  const image = dragImage(label);
  if (!image) {
    return { started: false, message: "ドラッグ用の画像を生成できませんでした" };
  }
  return new Promise<DragOutcome>((resolve) => {
    let settled = false;
    const timeout = window.setTimeout(() => {
      if (settled) return;
      settled = true;
      resolve({ started: true, message: "ドラッグの終了を確認できませんでした。もう一度お試しください。" });
    }, 120_000);
    const onEvent = new Channel<DragCallback>();
    onEvent.onmessage = (message) => {
      if (settled) return;
      settled = true;
      window.clearTimeout(timeout);
      resolve({ started: true, result: message.result });
    };
    invoke("plugin:drag|start_drag", {
      item: [filepath],
      image,
      options: { mode: "copy" },
      onEvent,
    }).catch((error) => {
      if (settled) return;
      settled = true;
      window.clearTimeout(timeout);
      resolve({ started: false, message: `ドラッグを開始できませんでした: ${String(error)}` });
    });
  });
}
