import { useEffect, useRef, useState } from "react";
import { WS_BASE_URL } from "@/services/api-client";

export interface GenreAnalysisResult {
  track_id: number;
  title: string;
  artist: string;
  old_genre: string;
  new_genre: string;
}

export interface GenreAnalysisState {
  type: string; // idle | start | processing | complete | error | cancelled
  total: number;
  current: number;
  message: string;
  processed: number;
  errors: number;
  updated: number;
  current_track: string;
  recent_results: GenreAnalysisResult[];
  failed_track_ids: number[];
}

const INITIAL_STATE: GenreAnalysisState = {
  type: "idle",
  total: 0,
  current: 0,
  message: "",
  processed: 0,
  errors: 0,
  updated: 0,
  current_track: "",
  recent_results: [],
  failed_track_ids: [],
};

/**
 * /ws/genres/analysis に接続し、バックグラウンドジャンル解析の進捗・結果ログを購読する。
 */
export function useGenreAnalysis() {
  const [state, setState] = useState<GenreAnalysisState>(INITIAL_STATE);
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    let disposed = false;

    const connect = () => {
      if (disposed) return;
      const ws = new WebSocket(`${WS_BASE_URL}/genres/analysis`);
      wsRef.current = ws;

      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          setState((prev) => ({ ...prev, ...data }));
        } catch {
          // 不正なメッセージは無視
        }
      };

      ws.onclose = () => {
        if (disposed) return;
        reconnectTimer.current = setTimeout(connect, 3000);
      };
    };

    connect();

    return () => {
      disposed = true;
      if (reconnectTimer.current) clearTimeout(reconnectTimer.current);
      wsRef.current?.close();
    };
  }, []);

  const isRunning = state.type === "start" || state.type === "processing";

  return { state, isRunning };
}
