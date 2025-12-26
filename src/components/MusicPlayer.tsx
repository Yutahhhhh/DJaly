import { useState, useEffect, useRef, useCallback } from "react";
import { API_BASE_URL } from "@/services/api-client";
import { metadataService, FileMetadata } from "@/services/metadata";
import { usePlayerStore } from "@/stores/playerStore";
import { MiniPlayer } from "./music-player/MiniPlayer";
import { ExpandedPlayer } from "./music-player/ExpandedPlayer";
import {
  AUDIO_CONSTANTS,
  safePlayAudio,
  isAudioReadyForSeek,
  isTimeOffTarget,
  isInvalidZeroReset,
} from "@/lib/utils";

interface MusicPlayerProps {
  onLoadingChange?: (isLoading: boolean) => void;
}

export function MusicPlayer({ onLoadingChange }: MusicPlayerProps) {
  const {
    currentTrack: track,
    isPlaying,
    volume,
    seekRequest,
    setIsPlaying,
    setVolume,
    setProgress: setStoreProgress,
    setDuration: setStoreDuration,
    setTrack,
    clearSeekRequest,
  } = usePlayerStore();

  const [isExpanded, setIsExpanded] = useState(false);
  const [metadata, setMetadata] = useState<FileMetadata | null>(null);
  const [editedLyrics, setEditedLyrics] = useState("");
  const [isEditingLyrics, setIsEditingLyrics] = useState(false);
  const [aiArtworkInfo, setAiArtworkInfo] = useState<string | null>(null);
  const [isSaving, setIsSaving] = useState(false);
  const [progress, setProgress] = useState(0);

  const audioRef = useRef<HTMLAudioElement>(null);

  const targetSeekTimeRef = useRef<number | null>(null);
  const isSeekingActiveRef = useRef<boolean>(false);

  const performForcedSeek = useCallback(
    (time: number) => {
      const audio = audioRef.current;
      if (!audio) return;

      isSeekingActiveRef.current = true;
      targetSeekTimeRef.current = time;
      audio.currentTime = time;

      if (audio.paused) {
        safePlayAudio(audio);
      }

      AUDIO_CONSTANTS.SEEK_RETRY_DELAYS.forEach((delay, index) => {
        setTimeout(() => {
          if (!audio || targetSeekTimeRef.current === null) return;

          if (isTimeOffTarget(audio.currentTime, targetSeekTimeRef.current)) {
            audio.currentTime = targetSeekTimeRef.current;
          }

          if (index === AUDIO_CONSTANTS.SEEK_RETRY_DELAYS.length - 1) {
            isSeekingActiveRef.current = false;
            targetSeekTimeRef.current = null;
            clearSeekRequest();
          }
        }, delay);
      });
    },
    [clearSeekRequest]
  );

  const loadAudioSource = useCallback(
    (audio: HTMLAudioElement) => {
      if (!track) return;

      const newSrc = `${API_BASE_URL}/stream?path=${encodeURIComponent(
        track.filepath
      )}`;

      if (audio.src !== newSrc) {
        audio.src = newSrc;
        audio.load();
      }

      if (isPlaying && seekRequest === null) {
        const playWhenReady = () => {
          safePlayAudio(audio, () => setIsPlaying(false));
          audio.removeEventListener("loadeddata", playWhenReady);
        };

        if (isAudioReadyForSeek(audio)) {
          safePlayAudio(audio, () => setIsPlaying(false));
        } else {
          audio.addEventListener("loadeddata", playWhenReady);
        }
      }
    },
    [track, isPlaying, seekRequest, setIsPlaying]
  );

  const loadMetadata = useCallback(async () => {
    if (!track) return;

    try {
      const [data, lyricsData] = await Promise.all([
        metadataService.getMetadata(track.id),
        metadataService.getLyricsFromDB(track.id).catch(() => ({ content: "" })),
      ]);
      setMetadata(data);
      setEditedLyrics(lyricsData.content || data.lyrics || "");
    } finally {
      onLoadingChange?.(false);
    }
  }, [track, onLoadingChange]);

  useEffect(() => {
    if (!seekRequest || !audioRef.current) return;

    const audio = audioRef.current;

    if (isAudioReadyForSeek(audio)) {
      performForcedSeek(seekRequest);
    } else {
      targetSeekTimeRef.current = seekRequest;
      const onCanPlay = () => {
        if (targetSeekTimeRef.current !== null) {
          performForcedSeek(targetSeekTimeRef.current);
        }
        audio.removeEventListener("canplay", onCanPlay);
      };
      audio.addEventListener("canplay", onCanPlay);
      safePlayAudio(audio, () => {
        audio.removeEventListener("canplay", onCanPlay);
        clearSeekRequest();
      });
    }
  }, [seekRequest, performForcedSeek, clearSeekRequest]);

  useEffect(() => {
    if (audioRef.current) {
      audioRef.current.volume = volume;
    }
  }, [volume]);

  useEffect(() => {
    const audio = audioRef.current;
    if (!audio || !track || isSeekingActiveRef.current) return;

    if (isPlaying) {
      if (audio.paused) {
        safePlayAudio(audio, () => setIsPlaying(false));
      }
    } else {
      if (!audio.paused) {
        audio.pause();
      }
    }
  }, [isPlaying, track, setIsPlaying]);

  useEffect(() => {
    if (!track) return;

    onLoadingChange?.(true);
    setMetadata(null);
    setAiArtworkInfo(null);
    setProgress(0);

    if (audioRef.current) {
      loadAudioSource(audioRef.current);
    }

    loadMetadata();
  }, [track?.id, loadAudioSource, loadMetadata, onLoadingChange]);

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
        await metadataService.updateMetadata(track.id, {
          artwork_data: updates.artwork_data,
        });
      }
      const updated = await metadataService.getMetadata(track.id);
      setMetadata(updated);
    } catch (e) {
      console.error(e);
    } finally {
      setIsSaving(false);
    }
  };

  const handleTimeUpdate = useCallback(() => {
    if (!audioRef.current) return;

    const cur = audioRef.current.currentTime;

    if (
      isSeekingActiveRef.current &&
      targetSeekTimeRef.current !== null &&
      isInvalidZeroReset(cur)
    ) {
      audioRef.current.currentTime = targetSeekTimeRef.current;
      return;
    }

    setProgress(cur);
    setStoreProgress(cur);
  }, [setStoreProgress]);

  const handleDurationChange = useCallback(() => {
    if (audioRef.current) {
      setStoreDuration(audioRef.current.duration);
    }
  }, [setStoreDuration]);

  const handlePlaying = useCallback(() => {
    if (seekRequest !== null) {
      performForcedSeek(seekRequest);
    }
  }, [seekRequest, performForcedSeek]);

  const handlePlay = useCallback(() => {
    if (!isPlaying) setIsPlaying(true);
  }, [isPlaying, setIsPlaying]);

  const handlePause = useCallback(() => {
    if (!isSeekingActiveRef.current && isPlaying) {
      setIsPlaying(false);
    }
  }, [isPlaying, setIsPlaying]);

  const handleEnded = useCallback(() => {
    setIsPlaying(false);
    setStoreProgress(0);
  }, [setIsPlaying, setStoreProgress]);

  const handleSeek = useCallback(
    (ratio: number) => {
      if (audioRef.current && audioRef.current.duration) {
        audioRef.current.currentTime = ratio * audioRef.current.duration;
      }
    },
    []
  );

  if (!track) return null;

  return (
    <div
      className={`fixed bottom-0 left-0 right-0 bg-background border-t shadow-2xl transition-all duration-500 z-50 flex flex-col ${
        isExpanded ? "h-[50vh]" : "h-20"
      }`}
    >
      <audio
        ref={audioRef}
        preload="auto"
        onPlay={handlePlay}
        onPause={handlePause}
        onEnded={handleEnded}
        onTimeUpdate={handleTimeUpdate}
        onDurationChange={handleDurationChange}
        onPlaying={handlePlaying}
      />

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

      <MiniPlayer
        track={track}
        metadata={metadata}
        isPlaying={isPlaying}
        progress={progress}
        duration={audioRef.current?.duration || track.duration}
        volume={volume}
        isExpanded={isExpanded}
        onPlayPause={() => setIsPlaying(!isPlaying)}
        onSkipBack={() => {}}
        onSkipForward={() => {}}
        onVolumeChange={setVolume}
        onToggleExpand={() => setIsExpanded(!isExpanded)}
        onClose={() => {
          setIsPlaying(false);
          setTrack(null);
        }}
        onSeek={handleSeek}
      />
    </div>
  );
}
