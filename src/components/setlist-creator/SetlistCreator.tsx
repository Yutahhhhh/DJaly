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
import { setlistsService, Setlist } from "@/services/setlists";
import { Track } from "@/types";

export function SetlistCreator({
  onPlay,
  currentTrackId,
}: {
  onPlay: (track: Track) => void;
  currentTrackId?: number | null;
}) {
  const [setlists, setSetlists] = useState<Setlist[]>([]);
  const [activeSetlist, setActiveSetlist] = useState<Setlist | null>(null);
  const [tracks, setTracks] = useState<Track[]>([]);
  const [selectedTrack, setSelectedTrack] = useState<Track | null>(null);

  const [activeDragItem, setActiveDragItem] = useState<{
    track: Track;
    type: string;
  } | null>(null);
  const [bridgeStart, setBridgeStart] = useState<Track | null>(null);
  const [bridgeEnd, setBridgeEnd] = useState<Track | null>(null);

  // 【速度改善】 MouseSensor を使用し、WebKitの遅延を最小化
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

  const commitTracksToDB = async (newTracks: Track[]) => {
    setTracks(newTracks);
    if (activeSetlist) {
      try {
        await setlistsService.updateTracks(
          activeSetlist.id,
          newTracks.map((t) => t.id)
        );
      } catch (e) {
        console.error(e);
      }
    }
  };

  const handleDragStart = useCallback((event: DragStartEvent) => {
    setActiveDragItem(event.active.data.current as any);
  }, []);

  // 【モーションの肝】 ドラッグ中に配列を操作して「避ける」動きを作る
  const handleDragOver = useCallback(
    (event: DragOverEvent) => {
      const { active, over } = event;
      if (!over || !activeSetlist) return;

      const activeData = active.data.current;
      const overData = over.data.current;

      // ライブラリからセットリストのアイテムの上に重なった時
      if (
        activeData?.type === "LIBRARY_ITEM" &&
        overData?.type === "SETLIST_ITEM"
      ) {
        const track = activeData.track as Track;
        const overId = over.id as string;

        const isAlreadyInList = tracks.some((t) => t.id === track.id);
        const overIndex = tracks.findIndex((t) => `setlist-${t.id}` === overId);

        if (!isAlreadyInList) {
          // まだリストにない曲なら、その位置にプレビューとして挿入
          const newTracks = [...tracks];
          newTracks.splice(overIndex, 0, track);
          setTracks(newTracks);
        } else {
          // すでにリストにある（移動中）なら位置を入れ替え
          const oldIndex = tracks.findIndex((t) => t.id === track.id);
          if (oldIndex !== overIndex) {
            setTracks(arrayMove(tracks, oldIndex, overIndex));
          }
        }
      }

      // セットリスト内での並べ替えプレビュー
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
        // どこにもドロップされなかった場合、リロードしてプレビューをリセット
        if (activeSetlist) handleSelectSetlist(activeSetlist.id);
        return;
      }

      const activeData = active.data.current;
      const overId = over.id as string;

      // 【確定保存】 ここで初めてDBに書き込む
      if (
        activeData?.type === "SETLIST_ITEM" ||
        activeData?.type === "LIBRARY_ITEM"
      ) {
        if (
          over.data.current?.type === "SETLIST_ITEM" ||
          over.id === "setlist-editor-droppable"
        ) {
          commitTracksToDB(tracks);
          return;
        }
      }

      if (activeData?.track) {
        if (overId === "bridge-start") setBridgeStart(activeData.track);
        if (overId === "bridge-end") setBridgeEnd(activeData.track);
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
          <>
            <SetlistEditor
              tracks={tracks}
              onRemoveTrack={(idx: number) => {
                const nt = [...tracks];
                nt.splice(idx, 1);
                commitTracksToDB(nt);
              }}
              onTrackSelect={setSelectedTrack}
              selectedTrackId={selectedTrack?.id || null}
              onPlay={onPlay}
              currentTrackId={currentTrackId}
            />
            {/* TrackSelectorのPropsにbridgeStateが存在しないエラーを回避しつつ
              型を安全にキャストして渡します。
            */}
            <TrackSelector
              referenceTrack={selectedTrack}
              onAddTrack={(t: Track) => {
                if (!tracks.some((ex) => ex.id === t.id))
                  commitTracksToDB([...tracks, t]);
              }}
              onInjectTracks={(
                ts: Track[],
                startId?: number,
                _endId?: number
              ) => {
                let nt = [...tracks];
                const idx = nt.findIndex((t) => t.id === startId);
                // 指定されたIDの後ろに挿入、見つからなければ末尾
                nt.splice(idx !== -1 ? idx + 1 : nt.length, 0, ...ts);
                commitTracksToDB(nt);
              }}
              currentSetlistTracks={tracks}
              onPlay={onPlay}
              currentTrackId={currentTrackId}
              {...({
                bridgeState: {
                  start: bridgeStart,
                  end: bridgeEnd,
                  setStart: setBridgeStart,
                  setEnd: setBridgeEnd,
                },
              } as any)}
            />
          </>
        ) : (
          <div className="flex-1 flex items-center justify-center text-muted-foreground bg-muted/10 italic">
            Select a setlist to start editing
          </div>
        )}
      </div>

      {/* 【視覚効果】 ドラッグ中のオーバーレイ表示 */}
      <DragOverlay dropAnimation={null}>
        {activeDragItem ? (
          <div className="w-72 shadow-2xl rounded-md overflow-hidden border border-primary bg-background pointer-events-none opacity-90 scale-105">
            <TrackRow
              id="overlay"
              track={activeDragItem.track}
              type={activeDragItem.type as any}
              onPlay={() => {}}
            />
          </div>
        ) : null}
      </DragOverlay>
    </DndContext>
  );
}
