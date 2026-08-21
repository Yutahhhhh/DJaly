import { useCallback, useEffect, useState } from "react";
import * as api from "./api/client";
import { PlaylistView } from "./components/PlaylistView";
import { TrackList } from "./components/TrackList";
import { Timeline } from "./components/Timeline";
import { CueEditor } from "./components/CueEditor";
import { ModeSwitcher } from "./components/ModeSwitcher";
import { BackupPanel } from "./components/BackupPanel";
import { ChangeSetPanel } from "./components/ChangeSetPanel";
import type { CuePoint, OperationMode, ServerStatus, Track } from "./types";

export function App() {
  const [status, setStatus] = useState<ServerStatus | null>(null);
  const [statusError, setStatusError] = useState<string | null>(null);

  const [knownTrackIds, setKnownTrackIds] = useState<number[]>([]);
  const [selectedTrackId, setSelectedTrackId] = useState<number | null>(null);
  const [track, setTrack] = useState<Track | null>(null);
  const [trackError, setTrackError] = useState<string | null>(null);
  const [trackLoading, setTrackLoading] = useState(false);

  const [selectedCueId, setSelectedCueId] = useState<string | null>(null);
  const [proposedCues, setProposedCues] = useState<CuePoint[]>([]);

  const refreshStatus = useCallback(() => {
    api
      .getStatus()
      .then(setStatus)
      .catch((e) => setStatusError(e instanceof Error ? e.message : String(e)));
  }, []);

  useEffect(() => {
    refreshStatus();
  }, [refreshStatus]);

  const loadTrack = useCallback((trackId: number) => {
    setTrackLoading(true);
    setTrackError(null);
    setSelectedCueId(null);
    setProposedCues([]);
    setTrack(null);
    api
      .getTrack(trackId)
      .then(setTrack)
      .catch((e) => setTrackError(e instanceof Error ? e.message : String(e)))
      .finally(() => setTrackLoading(false));
  }, []);

  function handleSelectTrack(trackId: number) {
    setSelectedTrackId(trackId);
    setKnownTrackIds((prev) => (prev.includes(trackId) ? prev : [...prev, trackId]));
    loadTrack(trackId);
  }

  function refreshCues() {
    if (selectedTrackId != null) {
      api
        .getCues(selectedTrackId)
        .then((res) => setTrack((prev) => (prev ? { ...prev, cues: res.cues } : prev)))
        .catch((e) => setTrackError(e instanceof Error ? e.message : String(e)));
    }
  }

  const writeAllowed = status?.mode !== "readonly";

  function handleDragCue(cue: CuePoint, newPositionMs: number) {
    if (!writeAllowed || selectedTrackId == null) return;
    api
      .updateCue(cue.id, { track_id: selectedTrackId, position_ms: newPositionMs })
      .then(() => refreshCues())
      .catch((e) => setTrackError(e instanceof Error ? e.message : String(e)));
  }

  function handleAddCueAt(positionMs: number) {
    if (!writeAllowed || selectedTrackId == null) return;
    api
      .addMemoryCue({ track_id: selectedTrackId, position_ms: positionMs, name: "New cue" })
      .then(() => refreshCues())
      .catch((e) => setTrackError(e instanceof Error ? e.message : String(e)));
  }

  function handleModeChanged(mode: OperationMode) {
    setStatus((prev) => (prev ? { ...prev, mode } : prev));
    refreshStatus();
  }

  return (
    <div className="app">
      <header className="app__header">
        <h1>Rekordbox MCP — Cue &amp; Playlist Studio</h1>
        {status && (
          <div className="app__status">
            <span className={`app__status-dot${status.db_connected ? " app__status-dot--ok" : " app__status-dot--bad"}`} />
            {status.db_connected ? "DB connected" : "DB disconnected"}
            {" · "}
            {status.rekordbox_running ? "Rekordbox running" : "Rekordbox closed"}
            {" · "}
            mode: <strong>{status.mode}</strong>
            {" · "}
            {status.track_count} tracks / {status.playlist_count} playlists
          </div>
        )}
        {statusError && <div className="error-banner">{statusError}</div>}
      </header>

      <div className="app__body">
        <aside className="app__sidebar">
          <PlaylistView onSelectTrack={handleSelectTrack} selectedTrackId={selectedTrackId} />
          <TrackList
            knownTrackIds={knownTrackIds}
            selectedTrackId={selectedTrackId}
            onSelectTrack={handleSelectTrack}
          />
          <ModeSwitcher mode={status?.mode ?? null} onModeChanged={handleModeChanged} />
          <BackupPanel />
        </aside>

        <main className="app__main">
          <ChangeSetPanel />
          {trackLoading && <p>Loading track…</p>}
          {trackError && <div className="error-banner">{trackError}</div>}
          {!track && !trackLoading && (
            <p className="app__empty-hint">Select a playlist track (or load one by ID) to begin.</p>
          )}
          {track && (
            <>
              <h2>
                {track.title} <span className="app__track-meta">— {track.bpm.toFixed(1)} BPM · {(track.duration_ms / 1000).toFixed(0)}s</span>
              </h2>
              <Timeline
                track={track}
                proposedCues={proposedCues}
                selectedCueId={selectedCueId}
                onSelectCue={(cue) => setSelectedCueId(cue.id)}
                onDragCue={handleDragCue}
                onAddCueAt={handleAddCueAt}
              />
              <CueEditor
                trackId={track.id}
                cues={track.cues}
                selectedCueId={selectedCueId}
                onSelectCue={(cue) => setSelectedCueId(cue.id)}
                onCuesChanged={refreshCues}
                proposedCues={proposedCues}
                onProposedCuesChanged={setProposedCues}
                writeAllowed={writeAllowed}
              />
            </>
          )}
        </main>
      </div>
    </div>
  );
}
