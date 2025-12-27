import { useRef, useCallback, useEffect } from "react";
import { API_BASE_URL } from "@/services/api-client";
import {
  AUDIO_CONSTANTS,
  safePlayAudio,
  isAudioReadyForSeek,
  isTimeOffTarget,
} from "@/lib/utils";

interface UseAudioPreviewOptions {
  maxDuration?: number; // プレビューの最大再生時間（ミリ秒）
  preRollTime?: number; // 指定位置の何秒前から再生するか
  onPlayStart?: () => void;
  onPlayEnd?: () => void;
  onError?: (error: Error) => void;
}

/**
 * オーディオのプレビュー再生を管理するカスタムフック
 * MusicPlayerと同様の強力なシーク処理を提供
 */
export function useAudioPreview(options: UseAudioPreviewOptions = {}) {
  const {
    maxDuration = 10000,
    preRollTime = 1,
    onPlayStart,
    onPlayEnd,
    onError,
  } = options;

  const audioRef = useRef<HTMLAudioElement | null>(null);
  const targetSeekTimeRef = useRef<number | null>(null);
  const isSeekingActiveRef = useRef<boolean>(false);
  const stopTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  /**
   * 強制的なシーク処理
   * ブラウザによる勝手な0秒リセットを防ぐため、複数回リトライする
   */
  const performForcedSeek = useCallback((audio: HTMLAudioElement, time: number) => {
    isSeekingActiveRef.current = true;
    targetSeekTimeRef.current = time;
    audio.currentTime = time;

    if (audio.paused) {
      safePlayAudio(audio);
    }

    // AUDIO_CONSTANTS.SEEK_RETRY_DELAYSのタイミングで複数回シークを試行
    AUDIO_CONSTANTS.SEEK_RETRY_DELAYS.forEach((delay, index) => {
      setTimeout(() => {
        if (!audio || targetSeekTimeRef.current === null) return;

        if (isTimeOffTarget(audio.currentTime, targetSeekTimeRef.current)) {
          audio.currentTime = targetSeekTimeRef.current;
        }

        // 最後のリトライが完了したらシーク処理を終了
        if (index === AUDIO_CONSTANTS.SEEK_RETRY_DELAYS.length - 1) {
          isSeekingActiveRef.current = false;
          targetSeekTimeRef.current = null;
        }
      }, delay);
    });
  }, []);

  /**
   * 指定されたファイルパスと位置からプレビュー再生を開始
   */
  const playPreview = useCallback(
    (filePath: string, timestamp?: number) => {
      // 既存の再生を停止
      if (audioRef.current) {
        audioRef.current.pause();
        audioRef.current = null;
      }

      if (stopTimerRef.current) {
        clearTimeout(stopTimerRef.current);
        stopTimerRef.current = null;
      }

      // 新しいAudioエレメントを作成
      const audio = new Audio(
        `${API_BASE_URL}/stream?path=${encodeURIComponent(filePath)}`
      );
      audioRef.current = audio;

      // 再生開始位置を計算（指定位置のpreRollTime秒前から）
      const startTime =
        timestamp !== undefined ? Math.max(0, timestamp - preRollTime) : 0;

      onPlayStart?.();

      /**
       * オーディオが再生可能になったらシークして再生
       */
      const onCanPlay = () => {
        if (!audioRef.current || audioRef.current !== audio) return;

        // オーディオがシーク可能な状態か確認
        if (isAudioReadyForSeek(audio)) {
          performForcedSeek(audio, startTime);
        } else {
          // まだ準備ができていない場合は、もう少し待つ
          audio.currentTime = startTime;
          safePlayAudio(audio).catch((err) => {
            console.error("再生開始に失敗:", err);
            onError?.(err as Error);
            onPlayEnd?.();
          });
        }

        audio.removeEventListener("canplay", onCanPlay);
      };

      audio.addEventListener("canplay", onCanPlay);

      /**
       * エラーハンドリング
       */
      audio.onerror = () => {
        const error = new Error("オーディオの読み込みに失敗しました");
        console.error(error);
        onError?.(error);
        onPlayEnd?.();
      };

      /**
       * 再生終了時の処理
       */
      audio.onended = () => {
        if (stopTimerRef.current) {
          clearTimeout(stopTimerRef.current);
          stopTimerRef.current = null;
        }
        onPlayEnd?.();
      };

      /**
       * 最大再生時間後に自動停止
       */
      stopTimerRef.current = setTimeout(() => {
        if (audioRef.current === audio) {
          audio.pause();
          onPlayEnd?.();
        }
        stopTimerRef.current = null;
      }, maxDuration);

      // オーディオのロードを開始
      audio.load();
    },
    [maxDuration, preRollTime, onPlayStart, onPlayEnd, onError, performForcedSeek]
  );

  /**
   * プレビュー再生を停止
   */
  const stopPreview = useCallback(() => {
    if (audioRef.current) {
      audioRef.current.pause();
      audioRef.current = null;
    }

    if (stopTimerRef.current) {
      clearTimeout(stopTimerRef.current);
      stopTimerRef.current = null;
    }

    onPlayEnd?.();
  }, [onPlayEnd]);

  /**
   * クリーンアップ
   */
  useEffect(() => {
    return () => {
      if (audioRef.current) {
        audioRef.current.pause();
        audioRef.current = null;
      }

      if (stopTimerRef.current) {
        clearTimeout(stopTimerRef.current);
        stopTimerRef.current = null;
      }
    };
  }, []);

  return {
    playPreview,
    stopPreview,
  };
}
