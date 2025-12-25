import { useState, useEffect, useRef } from "react";
import { API_BASE_URL } from "@/services/api-client";
import { metadataService, FileMetadata } from "@/services/metadata";
import { usePlayerStore } from "@/stores/playerStore";
import { MiniPlayer } from "./music-player/MiniPlayer";
import { ExpandedPlayer } from "./music-player/ExpandedPlayer";

interface MusicPlayerProps {
  onLoadingChange?: (isLoading: boolean) => void;
}

export function MusicPlayer({
  onLoadingChange,
}: MusicPlayerProps) {
  const { 
    currentTrack: track, 
    isPlaying, 
    volume, 
    setIsPlaying, 
    setVolume, 
    setProgress: setStoreProgress,
    setDuration: setStoreDuration,
    setTrack
  } = usePlayerStore();

  const [isExpanded, setIsExpanded] = useState(false);
  const [metadata, setMetadata] = useState<FileMetadata | null>(null);
  const [editedLyrics, setEditedLyrics] = useState("");
  const [isEditingLyrics, setIsEditingLyrics] = useState(false);
  const [aiArtworkInfo, setAiArtworkInfo] = useState<string | null>(null);
  const [isSaving, setIsSaving] = useState(false);
  const [progress, setProgress] = useState(0);

  const audioRef = useRef<HTMLAudioElement>(null);

  // Sync volume
  useEffect(() => {
    if (audioRef.current) {
      audioRef.current.volume = volume;
    }
  }, [volume]);

  // Sync play/pause
  useEffect(() => {
    if (audioRef.current) {
      if (isPlaying) {
        const playPromise = audioRef.current.play();
        if (playPromise !== undefined) {
          playPromise.catch((error) => {
            // Ignore AbortError (happens when src changes quickly)
            if (error.name !== "AbortError") {
              setIsPlaying(false);
            }
          });
        }
      } else {
        audioRef.current.pause();
      }
    }
  }, [isPlaying]);

  // 楽曲の読み込みとメタデータの取得
  useEffect(() => {
    if (track) {
      onLoadingChange?.(true);
      setMetadata(null);
      setAiArtworkInfo(null);
      setProgress(0);

      if (audioRef.current) {
        audioRef.current.src = `${API_BASE_URL}/stream?path=${encodeURIComponent(
          track.filepath
        )}`;
        // Auto play is handled by the store state (play() sets isPlaying to true)
        if (isPlaying) {
          const playPromise = audioRef.current.play();
          if (playPromise !== undefined) {
            playPromise.catch((error) => {
              if (error.name !== "AbortError") {
                setIsPlaying(false);
              }
            });
          }
        }
      }

      // サービス層を使用してメタデータを取得
      Promise.all([
        metadataService.getMetadata(track.id),
        metadataService.getLyricsFromDB(track.id).catch(() => ({ content: "" }))
      ])
        .then(([data, lyricsData]) => {
          setMetadata(data);
          const lyrics = lyricsData.content || data.lyrics || "";
          setEditedLyrics(lyrics);
        })
        .finally(() => onLoadingChange?.(false));
    } else {
      setIsPlaying(false);
    }
  }, [track?.id]); // Only re-run if track ID changes

  // ファイルメタデータの更新適用
  const handleApplyChanges = async (updates: {
    lyrics?: string;
    artwork_data?: string;
  }) => {
    if (!track) return;
    setIsSaving(true);
    try {
      if (updates.lyrics !== undefined) {
        await metadataService.updateLyricsInDB(track.id, updates.lyrics);
      }
      
      if (updates.artwork_data) {
        await metadataService.updateMetadata(track.id, { artwork_data: updates.artwork_data });
      }

      // 更新後に最新状態を再ロード
      const updated = await metadataService.getMetadata(track.id);
      setMetadata(updated);
    } catch (e) {
      console.error("Failed to apply metadata updates:", e);
    } finally {
      setIsSaving(false);
    }
  };

  if (!track) return null;

  return (
    <div
      className={`fixed bottom-0 left-0 right-0 bg-background border-t shadow-2xl transition-all duration-500 z-50 flex flex-col ${
        isExpanded ? "h-[50vh]" : "h-20"
      }`}
    >
      <audio
        ref={audioRef}
        onTimeUpdate={() => {
            const currentTime = audioRef.current?.currentTime || 0;
            setProgress(currentTime);
            setStoreProgress(currentTime);
        }}
        onDurationChange={() => setStoreDuration(audioRef.current?.duration || 0)}
        onEnded={() => setIsPlaying(false)}
      />

      {/* 展開時ビュー */}
      {isExpanded && (
        <ExpandedPlayer
          track={track}
          metadata={metadata}
          progress={progress}
          editedLyrics={editedLyrics}
          isEditingLyrics={isEditingLyrics}
          isSaving={isSaving}
          aiArtworkInfo={aiArtworkInfo}
          onClose={() => setIsExpanded(false)}
          onApplyChanges={handleApplyChanges}
          setEditedLyrics={setEditedLyrics}
          setIsEditingLyrics={setIsEditingLyrics}
          setAiArtworkInfo={setAiArtworkInfo}
        />
      )}

      {/* ミニプレイヤーエリア */}
      <MiniPlayer
        track={track}
        metadata={metadata}
        isPlaying={isPlaying}
        progress={progress}
        duration={audioRef.current?.duration || track.duration}
        volume={volume}
        isExpanded={isExpanded}
        onPlayPause={() => setIsPlaying(!isPlaying)}
        onSkipBack={() => {}} // TODO: Implement skip back
        onSkipForward={() => {}} // TODO: Implement skip forward
        onVolumeChange={setVolume}
        onToggleExpand={() => setIsExpanded(!isExpanded)}
        onClose={() => {
          setIsPlaying(false);
          setTrack(null);
        }}
        onSeek={(ratio) => {
          if (audioRef.current) {
            audioRef.current.currentTime = ratio * audioRef.current.duration;
          }
        }}
      />
    </div>
  );
}
