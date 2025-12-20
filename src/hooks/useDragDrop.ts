import { useState, useCallback } from "react";

interface UseDragDropOptions<T> {
  /**
   * 有効なアイテムがドロップされた時のコールバック
   */
  onDrop: (data: T, type: string) => void;
  /**
   * ドラッグイベントからデータをパースする関数
   */
  parseData: (e: React.DragEvent) => { data: T | null; type: string };
  /**
   * ドロップを有効にするかどうか
   */
  enableDrop?: boolean;
}

export function useDragDrop<T>({
  onDrop,
  parseData,
  enableDrop = true,
}: UseDragDropOptions<T>) {
  const [isDraggingOver, setIsDraggingOver] = useState(false);

  const handleDragOver = useCallback(
    (e: React.DragEvent) => {
      if (!enableDrop) return;

      // Tauri/WebKitではpreventDefaultしないとドロップを受け付けない
      e.preventDefault();

      // ドラッグ中の表示効果
      e.dataTransfer.dropEffect = "copy";

      if (!isDraggingOver) {
        setIsDraggingOver(true);
      }
    },
    [enableDrop, isDraggingOver]
  );

  const handleDragEnter = useCallback(
    (e: React.DragEvent) => {
      if (!enableDrop) return;
      e.preventDefault();
      setIsDraggingOver(true);
    },
    [enableDrop]
  );

  const handleDragLeave = useCallback((e: React.DragEvent) => {
    // 子要素に移動した際のがたつきを防止
    if (e.relatedTarget && e.currentTarget.contains(e.relatedTarget as Node)) {
      return;
    }
    setIsDraggingOver(false);
  }, []);

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      if (!enableDrop) return;
      e.preventDefault();
      setIsDraggingOver(false);

      try {
        const { data, type } = parseData(e);
        if (data) {
          onDrop(data, type);
        }
      } catch (err) {
        console.error("Drop processing failed", err);
      }
    },
    [enableDrop, onDrop, parseData]
  );

  return {
    isDraggingOver,
    dragHandlers: {
      onDragOver: handleDragOver,
      onDragEnter: handleDragEnter,
      onDragLeave: handleDragLeave,
      onDrop: handleDrop,
    },
  };
}

/**
 * トラックデータのパースヘルパー
 * Tauri環境で最も安定する text/plain ベースのJSON通信を使用
 */
export function parseTrackData<T>(e: React.DragEvent): {
  data: T | null;
  type: string;
} {
  // WebKitでは dragOver 中は getData が空になる制約があるため、
  // drop イベント時にのみデータが取得可能
  const rawData = e.dataTransfer.getData("text/plain");
  const type = e.dataTransfer.getData("djaly-type") || "NEW_TRACK";

  if (rawData && rawData.trim().startsWith("{")) {
    try {
      return { data: JSON.parse(rawData) as T, type };
    } catch (e) {
      console.warn("Failed to parse track JSON", e);
    }
  }
  return { data: null, type };
}
