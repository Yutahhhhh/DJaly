import { useState, useEffect, useCallback } from "react";
import {
  DndContext,
  DragEndEvent,
  MouseSensor,
  useSensor,
  useSensors,
  rectIntersection,
  DragOverEvent,
  DragStartEvent,
  DragOverlay,
} from "@dnd-kit/core";
import { arrayMove } from "@dnd-kit/sortable";

import { SetlistSidebar } from "./SetlistSidebar";
import { SetlistEditor } from "./SetlistEditor";
import { TrackSelector } from "./TrackSelector";
import { TrackRow } from "./TrackRow";
import { setlistsService, Setlist, SetlistTrack } from "@/services/setlists";
import { Track } from "@/types";

export function SetlistCreator() {
  const [setlists, setSetlists] = useState<Setlist[]>([]);
  const [activeSetlist, setActiveSetlist] = useState<Setlist | null>(null);
  const [tracks, setTracks] = useState<SetlistTrack[]>([]);
  const [selectedTrack, setSelectedTrack] = useState<Track | null>(null);

  const [activeDragItem, setActiveDragItem] = useState<{
    track: Track;
    type: string;
  } | null>(null);
  const [bridgeStart, setBridgeStart] = useState<Track | null>(null);
  const [bridgeEnd, setBridgeEnd] = useState<Track | null>(null);

  const sensors = useSensors(
    useSensor(MouseSensor, {
      activationConstraint: { distance: 5 },
    })
  );

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
      const t = await setlistsService.getTracks(id);
      setTracks(t);
      setSelectedTrack(null);
    }
  };

  /**
   * DBへの永続化処理
   * 各楽曲の wordplay_json をチェックし、前の楽曲との整合性が取れない場合は削除する
   */
  const commitTracksToDB = async (newTracks: (Track | SetlistTrack)[]) => {
    if (activeSetlist) {
      // 1. 整合性チェック: 前の楽曲が変わっていたら wordplay_json を無効化する
      const validatedTracks = newTracks.map((track, index) => {
        const st = track as SetlistTrack;
        if (!st.wordplay_json) return st;

        try {
          const wp = JSON.parse(st.wordplay_json);
          const prevTrack = index > 0 ? newTracks[index - 1] : null;

          // 前の曲が存在しない、またはワードプレイが想定している接続元IDと一致しない場合は不整合とみなす
          // 型の揺れを考慮して loose equality ( != ) を使用
          if (!prevTrack || wp.from_track_id != prevTrack.id) {
            console.log(
              `Wordplay inconsistency detected for track ${st.title}. Clearing metadata.`
            );
            return { ...st, wordplay_json: null };
          }
        } catch (e) {
          return { ...st, wordplay_json: null };
        }
        return st;
      });

      // UIに即座に反映 (楽観的アップデート)
      setTracks(validatedTracks as SetlistTrack[]);

      try {
        const updatePayload = validatedTracks.map((t) => ({
          id: t.id,
          wordplay_json: t.wordplay_json || null,
        }));

        // 保存実行
        await setlistsService.updateTracks(activeSetlist.id, updatePayload);

        // 最終的な状態をDBから取得
        const updatedTracks = await setlistsService.getTracks(activeSetlist.id);
        setTracks(updatedTracks);
      } catch (e) {
        console.error("Failed to commit tracks:", e);
        // エラー時はバリデーション済みのローカルステートを維持 (サーバーとの同期は次回の操作に期待)
      }
    } else {
      setTracks(newTracks as SetlistTrack[]);
    }
  };

  const handleDeleteWordplay = async (setlistTrackId: number) => {
    if (!activeSetlist) return;
    try {
      await setlistsService.deleteWordplay(setlistTrackId);
      const updatedTracks = await setlistsService.getTracks(activeSetlist.id);
      setTracks(updatedTracks);
    } catch (e) {
      console.error("ワードプレイの削除に失敗しました:", e);
    }
  };

  const handleDragStart = useCallback((event: DragStartEvent) => {
    setActiveDragItem(event.active.data.current as any);
  }, []);

  const handleDragOver = useCallback(
    (event: DragOverEvent) => {
      const { active, over } = event;
      if (!over || !activeSetlist) return;

      const activeData = active.data.current;
      const overData = over.data.current;

      if (
        activeData?.type === "LIBRARY_ITEM" &&
        over.id === "setlist-editor-droppable"
      ) {
        const track = activeData.track as Track;
        const isAlreadyInList = tracks.some((t) => t.id === track.id);

        if (!isAlreadyInList) {
          setTracks([
            ...tracks,
            {
              ...track,
              setlist_track_id: 0,
              position: tracks.length,
            } as SetlistTrack,
          ]);
        }
      }

      if (
        activeData?.type === "LIBRARY_ITEM" &&
        overData?.type === "SETLIST_ITEM"
      ) {
        const track = activeData.track as Track;
        const overId = over.id as string;

        const isAlreadyInList = tracks.some((t) => t.id === track.id);
        const overIndex = tracks.findIndex((t) => `setlist-${t.id}` === overId);

        if (!isAlreadyInList) {
          const newTracks = [...tracks];
          newTracks.splice(overIndex, 0, {
            ...track,
            setlist_track_id: 0,
            position: overIndex,
          } as SetlistTrack);
          setTracks(newTracks);
        } else {
          const oldIndex = tracks.findIndex((t) => t.id === track.id);
          if (oldIndex !== overIndex) {
            setTracks(arrayMove(tracks, oldIndex, overIndex));
          }
        }
      }

      if (
        activeData?.type === "SETLIST_ITEM" &&
        overData?.type === "SETLIST_ITEM"
      ) {
        if (active.id !== over.id) {
          const oldIndex = tracks.findIndex(
            (t) => `setlist-${t.id}` === active.id
          );
          const newIndex = tracks.findIndex(
            (t) => `setlist-${t.id}` === over.id
          );
          setTracks(arrayMove(tracks, oldIndex, newIndex));
        }
      }
    },
    [tracks, activeSetlist]
  );

  const handleDragEnd = useCallback(
    (event: DragEndEvent) => {
      const { active, over } = event;
      setActiveDragItem(null);
      if (!over) {
        if (activeSetlist) handleSelectSetlist(activeSetlist.id);
        return;
      }

      const activeData = active.data.current;

      if (
        activeData?.type === "SETLIST_ITEM" ||
        activeData?.type === "LIBRARY_ITEM"
      ) {
        if (
          over.data.current?.type === "SETLIST_ITEM" ||
          over.id === "setlist-editor-droppable"
        ) {
          // 移動完了時に整合性チェックを実行
          commitTracksToDB(tracks);
          return;
        }
      }

      if (activeData?.track) {
        if (over.id === "bridge-start") setBridgeStart(activeData.track);
        if (over.id === "bridge-end") setBridgeEnd(activeData.track);
      }
    },
    [tracks, activeSetlist]
  );

  return (
    <DndContext
      sensors={sensors}
      collisionDetection={rectIntersection}
      onDragStart={handleDragStart}
      onDragOver={handleDragOver}
      onDragEnd={handleDragEnd}
    >
      <div className="h-full flex overflow-hidden w-full bg-background border-t">
        <SetlistSidebar
          setlists={setlists}
          activeSetlistId={activeSetlist?.id || null}
          onSelect={handleSelectSetlist}
          onCreate={(name) => setlistsService.create(name).then(loadSetlists)}
          onUpdateName={(id, name) =>
            setlistsService.update(id, { name }).then(loadSetlists)
          }
          onDelete={(id) => setlistsService.delete(id).then(loadSetlists)}
        />

        {activeSetlist ? (
          <div className="flex-1 flex min-w-0 divide-x divide-border">
            <SetlistEditor
              tracks={tracks}
              onRemoveTrack={(idx: number) => {
                const nt = [...tracks];
                nt.splice(idx, 1);
                commitTracksToDB(nt);
              }}
              onTrackSelect={setSelectedTrack}
              selectedTrackId={selectedTrack?.id || null}
              onDeleteWordplay={handleDeleteWordplay}
            />
            <TrackSelector
              referenceTrack={selectedTrack}
              onAddTrack={async (t: Track, wordplayData?: any) => {
                if (activeSetlist) {
                  const insertIndex = selectedTrack
                    ? tracks.findIndex((tr) => tr.id === selectedTrack.id) + 1
                    : tracks.length;

                  const wordplayWithContext = wordplayData
                    ? {
                        ...wordplayData,
                        from_track_id: selectedTrack?.id || null,
                      }
                    : null;

                  const newTrackObj = {
                    ...t,
                    setlist_track_id: 0,
                    position: insertIndex,
                    wordplay_json: wordplayWithContext
                      ? JSON.stringify(wordplayWithContext)
                      : null,
                  };

                  const newTracks = [...tracks];
                  newTracks.splice(insertIndex, 0, newTrackObj as SetlistTrack);

                  await commitTracksToDB(newTracks);
                }
              }}
              onInjectTracks={(
                ts: Track[],
                startId?: number,
                _endId?: number
              ) => {
                let nt = [...tracks];
                const idx = nt.findIndex((t) => t.id === startId);
                const tsWithMeta = ts.map(
                  (t) =>
                    ({ ...t, setlist_track_id: 0, position: 0 } as SetlistTrack)
                );
                nt.splice(idx !== -1 ? idx + 1 : nt.length, 0, ...tsWithMeta);
                commitTracksToDB(nt);
              }}
              currentSetlistTracks={tracks}
              bridgeState={{
                start: bridgeStart,
                end: bridgeEnd,
                setStart: setBridgeStart,
                setEnd: setBridgeEnd,
              }}
            />
          </div>
        ) : (
          <div className="flex-1 flex items-center justify-center text-muted-foreground bg-muted/10 italic">
            Select a setlist to start editing
          </div>
        )}
      </div>

      <DragOverlay dropAnimation={null}>
        {activeDragItem ? (
          <div className="w-72 shadow-2xl rounded-md overflow-hidden border border-primary bg-background pointer-events-none opacity-90 scale-105">
            <TrackRow
              id="overlay"
              track={activeDragItem.track}
              type={activeDragItem.type as any}
            />
          </div>
        ) : null}
      </DragOverlay>
    </DndContext>
  );
}
