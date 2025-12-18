import { useState, useEffect } from "react";
import { SetlistSidebar } from "./SetlistSidebar";
import { SetlistEditor } from "./SetlistEditor";
import { TrackSelector } from "./TrackSelector";
import { setlistsService, Setlist } from "@/services/setlists";
import { Track } from "@/types";

interface SetlistCreatorProps {
  onPlay: (track: Track) => void;
  currentTrackId?: number | null;
}

export function SetlistCreator({
  onPlay,
  currentTrackId,
}: SetlistCreatorProps) {
  const [setlists, setSetlists] = useState<Setlist[]>([]);
  const [activeSetlist, setActiveSetlist] = useState<Setlist | null>(null);
  const [tracks, setTracks] = useState<Track[]>([]);

  // Selection State for Recommendation
  const [selectedTrack, setSelectedTrack] = useState<Track | null>(null);

  useEffect(() => {
    loadSetlists();
  }, []);

  const loadSetlists = async () => {
    try {
      const data = await setlistsService.getAll();
      setSetlists(data);
    } catch (e) {
      console.error(e);
    }
  };

  const handleSelectSetlist = async (id: number) => {
    const setlist = setlists.find((s) => s.id === id);
    if (setlist) {
      setActiveSetlist(setlist);
      try {
        const t = await setlistsService.getTracks(id);
        setTracks(t);
        setSelectedTrack(null);
      } catch (e) {
        console.error(e);
      }
    }
  };

  const handleCreateSetlist = async (name: string) => {
    try {
      const newSetlist = await setlistsService.create(name);
      setSetlists([newSetlist, ...setlists]);
      handleSelectSetlist(newSetlist.id);
    } catch (e) {
      console.error(e);
    }
  };

  const handleUpdateName = async (id: number, name: string) => {
    try {
      const updated = await setlistsService.update(id, { name });
      setSetlists(setlists.map((s) => (s.id === id ? updated : s)));
      if (activeSetlist?.id === id) setActiveSetlist(updated);
    } catch (e) {
      console.error(e);
    }
  };

  const handleDeleteSetlist = async (id: number) => {
    if (!confirm("Are you sure?")) return;
    try {
      await setlistsService.delete(id);
      setSetlists(setlists.filter((s) => s.id !== id));
      if (activeSetlist?.id === id) {
        setActiveSetlist(null);
        setTracks([]);
      }
    } catch (e) {
      console.error(e);
    }
  };

  // --- Track Manipulation ---

  const saveTracks = async (newTracks: Track[]) => {
    setTracks(newTracks);
    if (activeSetlist) {
      const ids = newTracks.map((t) => t.id);
      try {
        await setlistsService.updateTracks(activeSetlist.id, ids);
      } catch (e) {
        console.error("Failed to save setlist", e);
      }
    }
  };

  const handleAddTrack = (track: Track) => {
    if (!activeSetlist) return;
    const newTracks = [...tracks, track];
    saveTracks(newTracks);
    setSelectedTrack(track);
  };

  // ★ 修正: トラック挿入ロジック
  const handleInjectTracks = (
    newTracks: Track[],
    startTrackId?: number,
    _endTrackId?: number
  ) => {
    if (!activeSetlist) return;

    let updatedList = [...tracks];

    if (startTrackId) {
      // Startの直後(Index + 1)に挿入
      const startIndex = updatedList.findIndex((t) => t.id === startTrackId);
      if (startIndex !== -1) {
        updatedList.splice(startIndex + 1, 0, ...newTracks);
      } else {
        // Startが見つからない場合は末尾
        updatedList = [...updatedList, ...newTracks];
      }
    } else {
      // 指定がなければ末尾
      updatedList = [...updatedList, ...newTracks];
    }

    saveTracks(updatedList);
  };

  const handleRemoveTrack = (index: number) => {
    const newTracks = [...tracks];
    newTracks.splice(index, 1);
    saveTracks(newTracks);
  };

  const handleReorder = (dragIndex: number, hoverIndex: number) => {
    const newTracks = [...tracks];
    const [removed] = newTracks.splice(dragIndex, 1);
    newTracks.splice(hoverIndex, 0, removed);
    saveTracks(newTracks);
  };

  return (
    <div className="h-full flex overflow-hidden">
      <SetlistSidebar
        setlists={setlists}
        activeSetlistId={activeSetlist?.id || null}
        onSelect={handleSelectSetlist}
        onCreate={handleCreateSetlist}
        onUpdateName={handleUpdateName}
        onDelete={handleDeleteSetlist}
      />

      {activeSetlist ? (
        <>
          <SetlistEditor
            tracks={tracks}
            onRemoveTrack={handleRemoveTrack}
            onReorder={handleReorder}
            onDropTrack={handleAddTrack}
            onTrackSelect={setSelectedTrack}
            selectedTrackId={selectedTrack?.id || null}
            onPlay={onPlay}
            currentTrackId={currentTrackId}
          />
          <TrackSelector
            referenceTrack={selectedTrack}
            onAddTrack={handleAddTrack}
            onInjectTracks={handleInjectTracks}
            currentSetlistTracks={tracks}
            onPlay={onPlay}
            currentTrackId={currentTrackId}
          />
        </>
      ) : (
        <div className="flex-1 flex items-center justify-center text-muted-foreground bg-muted/10">
          Select or create a setlist to start editing.
        </div>
      )}
    </div>
  );
}
