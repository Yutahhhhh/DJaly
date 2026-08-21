import { useEffect, useState } from "react";
import { getPlaylists, getPlaylistTracks } from "../api/client";
import type { Playlist } from "../types";

interface PlaylistViewProps {
  onSelectTrack: (trackId: number) => void;
  selectedTrackId?: number | null;
}

/** Playlist/folder browser: lists playlists, and the track IDs within the selected one. */
export function PlaylistView({ onSelectTrack, selectedTrackId }: PlaylistViewProps) {
  const [playlists, setPlaylists] = useState<Playlist[]>([]);
  const [selectedPlaylistId, setSelectedPlaylistId] = useState<string | null>(null);
  const [trackIds, setTrackIds] = useState<number[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getPlaylists()
      .then(setPlaylists)
      .catch((e) => setError(String(e)));
  }, []);

  useEffect(() => {
    if (!selectedPlaylistId) {
      setTrackIds([]);
      return;
    }
    setLoading(true);
    getPlaylistTracks(selectedPlaylistId)
      .then((res) => setTrackIds(res.track_ids))
      .catch((e) => setError(String(e)))
      .finally(() => setLoading(false));
  }, [selectedPlaylistId]);

  return (
    <div className="playlist-view">
      <h3>Playlists</h3>
      {error && <div className="error-banner">{error}</div>}
      <ul className="playlist-view__list">
        {playlists.map((p) => (
          <li
            key={p.id}
            className={`playlist-view__item${p.id === selectedPlaylistId ? " playlist-view__item--selected" : ""}`}
            onClick={() => setSelectedPlaylistId(p.id)}
          >
            {p.attribute === 1 ? "📁" : p.attribute === 2 ? "🧠" : "🎵"} {p.name}
          </li>
        ))}
        {playlists.length === 0 && <li className="playlist-view__empty">No playlists found</li>}
      </ul>

      {selectedPlaylistId && (
        <div className="playlist-view__tracks">
          <h4>Tracks {loading && "(loading...)"}</h4>
          <ul>
            {trackIds.map((tid) => (
              <li
                key={tid}
                className={`playlist-view__track${tid === selectedTrackId ? " playlist-view__track--selected" : ""}`}
                onClick={() => onSelectTrack(tid)}
              >
                Track #{tid}
              </li>
            ))}
            {trackIds.length === 0 && !loading && <li className="playlist-view__empty">Empty playlist</li>}
          </ul>
        </div>
      )}
    </div>
  );
}
