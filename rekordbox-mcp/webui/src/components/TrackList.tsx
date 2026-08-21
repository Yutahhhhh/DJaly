import { useState } from "react";

interface TrackListProps {
  knownTrackIds: number[];
  selectedTrackId: number | null;
  onSelectTrack: (trackId: number) => void;
}

/**
 * Track list panel. The Web API has no `/api/tracks` endpoint to list every
 * track in the library, so this component surfaces track IDs discovered via
 * playlists (knownTrackIds) plus a manual "load by ID" field for any track
 * whose cues you want to inspect directly.
 */
export function TrackList({ knownTrackIds, selectedTrackId, onSelectTrack }: TrackListProps) {
  const [manualId, setManualId] = useState("");

  function handleManualLoad(e: React.FormEvent) {
    e.preventDefault();
    const id = parseInt(manualId, 10);
    if (!Number.isNaN(id)) {
      onSelectTrack(id);
      setManualId("");
    }
  }

  const uniqueIds = Array.from(new Set(knownTrackIds)).sort((a, b) => a - b);

  return (
    <div className="track-list">
      <h3>Tracks</h3>
      <ul className="track-list__list">
        {uniqueIds.map((id) => (
          <li
            key={id}
            className={`track-list__item${id === selectedTrackId ? " track-list__item--selected" : ""}`}
            onClick={() => onSelectTrack(id)}
          >
            Track #{id}
          </li>
        ))}
        {uniqueIds.length === 0 && (
          <li className="track-list__empty">Select a playlist to discover tracks, or load one by ID below.</li>
        )}
      </ul>
      <form className="track-list__manual" onSubmit={handleManualLoad}>
        <input
          type="number"
          placeholder="Track ID"
          value={manualId}
          onChange={(e) => setManualId(e.target.value)}
        />
        <button type="submit">Load</button>
      </form>
    </div>
  );
}
