import { useState, useEffect, useMemo } from "react";
import { Track } from "@/types";
import { lyricsService } from "@/services/lyrics";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Badge } from "@/components/ui/badge";
import {
  Loader2,
  Link as LinkIcon,
  Music,
  MessageSquare,
  ChevronDown,
  ChevronUp,
  AlertCircle,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { usePlayerStore } from "@/stores/playerStore";
import { PlayButton } from "@/components/ui/PlayButton";
import { normalizeLyricsTimeTags } from "@/lib/utils";
import { WordplayPair, wordplayService } from "@/services/wordplay";
import { getErrorDetail } from "@/services/api-client";

interface WordTabProps {
  sourceTrack: Track | null;
  onAddTrack: (track: Track, wordplayData?: any) => void;
}

export function WordTab({ sourceTrack, onAddTrack }: WordTabProps) {
  const [lyricsText, setLyricsText] = useState("");
  const [keywordInput, setKeywordInput] = useState("");
  const [searchResults, setSearchResults] = useState<any[]>([]);
  const [loading, setLoading] = useState(false);
  const [lyricsNotFound, setLyricsNotFound] = useState(false);
  const [searching, setSearching] = useState(false);
  const [activeKeyword, setActiveKeyword] = useState<string | null>(null);
  const [isLyricsExpanded, setIsLyricsExpanded] = useState(true);
  const [approvedPairs, setApprovedPairs] = useState<WordplayPair[]>([]);
  const [loadingApproved, setLoadingApproved] = useState(false);
  const [approvedError, setApprovedError] = useState<string | null>(null);

  const { currentTrack, isPlaying } = usePlayerStore();

  useEffect(() => {
    if (!sourceTrack) {
      setApprovedPairs([]);
      setApprovedError(null);
      return;
    }

    let cancelled = false;
    setApprovedPairs([]);
    setApprovedError(null);
    const loadApproved = async (quiet = false) => {
      if (!quiet) setLoadingApproved(true);
      try {
        const result = await wordplayService.list({
          status: "approved",
          from_track_id: sourceTrack.id,
          limit: 100,
          offset: 0,
        });
        if (!cancelled) {
          setApprovedPairs(result.items);
          setApprovedError(null);
        }
      } catch (error) {
        if (!cancelled) {
          console.error("Failed to load approved wordplay", error);
          setApprovedError(getErrorDetail(error));
        }
      } finally {
        if (!cancelled) setLoadingApproved(false);
      }
    };

    loadApproved();
    const timer = window.setInterval(() => loadApproved(true), 30_000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [sourceTrack?.id]);

  const visibleApprovedPairs = useMemo(
    () => approvedPairs.filter((pair) => pair.from_track_id === sourceTrack?.id),
    [approvedPairs, sourceTrack?.id]
  );

  // 選択されたキーワードが最初に登場するタイムスタンプを特定
  const firstKeywordTimestamp = useMemo(() => {
    if (!activeKeyword || !lyricsText) return null;

    const lines = lyricsText.split("\n");
    for (const line of lines) {
      const timestampMatch = line.match(/\[(\d+):(\d+(?:\.\d+)?)\]/);
      const cleanLine = line.replace(/\[\d{1,2}:\d{2}(?:\.\d+)?\]/g, "").trim();

      if (
        cleanLine.toLowerCase().includes(activeKeyword.toLowerCase()) &&
        timestampMatch
      ) {
        return parseInt(timestampMatch[1]) * 60 + parseFloat(timestampMatch[2]);
      }
    }
    return null;
  }, [activeKeyword, lyricsText]);

  useEffect(() => {
    if (!sourceTrack) return;
    let cancelled = false;

    setLoading(true);
    setLyricsNotFound(false);
    setSearchResults([]);
    setActiveKeyword(null);
    setLyricsText("");
    setKeywordInput("");

    lyricsService
      .getLyrics(sourceTrack.id)
      .then((lyData) => {
        if (cancelled) return;
        setLyricsText(normalizeLyricsTimeTags(lyData.content || ""));
      })
      .catch((error) => {
        if (cancelled) return;
        console.error("Failed to load lyrics", error);
        setLyricsNotFound(true);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [sourceTrack?.id]);

  const handleKeywordSearch = async (kw: string) => {
    const normalized = kw.trim();
    if (normalized.length < 3) return;
    setActiveKeyword(normalized);
    setSearching(true);
    try {
      const results = await lyricsService.searchLyrics(normalized, sourceTrack?.id);
      setSearchResults(results);
    } catch (error) {
      console.error("Search failed", error);
    } finally {
      setSearching(false);
    }
  };

  // 遷移情報（どのフレーズで抜けて、どのフレーズで入るか）を付与してセットリストへ追加
  const handleAddWithMeta = (
    targetTrack: Track,
    matchedText: string,
    targetTs: number | null
  ) => {
    onAddTrack(targetTrack, {
      keyword: activeKeyword,
      source_phrase: activeKeyword || "",
      target_phrase: matchedText,
      from_timestamp: firstKeywordTimestamp,
      to_timestamp: targetTs,
    });
  };

  const handleAddApproved = (pair: WordplayPair) => {
    if (!pair.to_track) return;
    onAddTrack(pair.to_track, {
      pair_id: pair.id,
      from_track_id: pair.from_track_id,
      to_track_id: pair.to_track_id,
      keyword: pair.keyword,
      source_phrase: pair.source_phrase,
      target_phrase: pair.target_phrase,
      from_timestamp: pair.from_timestamp,
      to_timestamp: pair.to_timestamp,
      source_cue_end_timestamp: pair.source_cue_end_timestamp,
      target_intro_timestamp: pair.target_intro_timestamp,
      target_landing_timestamp: pair.target_landing_timestamp,
      source_cue_mode: pair.source_cue_mode,
      transition_notes: pair.transition_notes,
      source_url: pair.source_url,
      evidence_type: pair.evidence_type,
      verification_status: pair.verification_status,
    });
  };

  const renderedLyrics = useMemo(() => {
    if (!lyricsText) return null;

    const lines = lyricsText.split("\n");
    return lines.map((line, lineIdx) => {
      const timestampMatch = line.match(/\[(\d+):(\d+(?:\.\d+)?)\]/);
      const timestamp = timestampMatch
        ? parseInt(timestampMatch[1]) * 60 + parseFloat(timestampMatch[2])
        : null;
      // LRC タイムタグのみ除去 (歌詞中の [bracket] 表現を巻き込まない)
      const cleanLine = line.replace(/\[\d{1,2}:\d{2}(?:\.\d+)?\]/g, "").trim();

      if (!cleanLine) return <div key={lineIdx} className="h-4" />;

      return (
        <div
          key={lineIdx}
          className="group/line flex items-start gap-2 py-1 hover:bg-muted/30 rounded px-2 transition-colors"
        >
          <div className="flex-1 text-sm leading-relaxed">
            <span className="text-muted-foreground/70">{cleanLine}</span>
          </div>
          {timestamp !== null && (
            <PlayButton
              track={sourceTrack!}
              timestamp={timestamp}
              variant="ghost"
              size="icon"
              className="h-6 w-6 opacity-0 group-hover/line:opacity-100 shrink-0 mt-0.5 hover:text-green-500"
              iconClassName="h-3 w-3"
            />
          )}
        </div>
      );
    });
  }, [lyricsText, sourceTrack]);

  if (!sourceTrack) {
    return (
      <div className="flex-1 flex flex-col items-center justify-center text-muted-foreground p-10 text-center gap-4">
        <MessageSquare className="h-12 w-12 opacity-20" />
        <p className="text-sm italic">
          Select a track from the list to start lyrical analysis.
        </p>
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full bg-background overflow-hidden">
      {/* Header */}
      <div className="flex-none p-3 border-b bg-background z-20 shadow-sm flex items-center justify-between">
        <div className="flex items-center gap-3 min-w-0">
          <div className="h-10 w-10 rounded bg-primary/10 flex items-center justify-center shrink-0">
            <Music className="h-5 w-5 text-primary" />
          </div>
          <div className="flex items-center gap-2 min-w-0">
            <div className="min-w-0">
              <div className="text-sm font-bold truncate leading-none mb-1">
                {sourceTrack.title}
              </div>
              <div className="text-[10px] text-muted-foreground truncate uppercase">
                {sourceTrack.artist}
              </div>
            </div>
            <PlayButton
              track={sourceTrack}
              timestamp={firstKeywordTimestamp}
              variant="ghost"
              size="icon"
              className={cn(
                "h-8 w-8 shrink-0 transition-all rounded-full hover:bg-accent",
                currentTrack?.id === sourceTrack.id && isPlaying
                  ? "text-green-500"
                  : "text-muted-foreground"
              )}
              iconClassName={cn(
                "h-4 w-4",
                currentTrack?.id === sourceTrack.id &&
                  isPlaying &&
                  "fill-current"
              )}
              showPauseWhenPlaying={true}
            />
          </div>
        </div>

        <div className="flex items-center gap-2">
          {loading && (
            <Loader2 className="h-4 w-4 animate-spin text-primary/50" />
          )}
          <Button
            variant="ghost"
            size="sm"
            className="h-8 text-[10px] font-bold uppercase gap-1 text-muted-foreground"
            onClick={() => setIsLyricsExpanded(!isLyricsExpanded)}
          >
            {isLyricsExpanded ? (
              <ChevronUp className="h-4 w-4" />
            ) : (
              <ChevronDown className="h-4 w-4" />
            )}
            {isLyricsExpanded ? "Collapse" : "Expand"}
          </Button>
        </div>
      </div>

      {/* Approved registry connections are available even when lyrics are missing. */}
      <section className="shrink-0 border-b bg-primary/[0.025]" aria-label="承認済みワードプレイ">
        <div className="flex items-center justify-between px-4 py-2">
          <div className="flex items-center gap-2">
            <span className="text-[10px] font-black uppercase tracking-wider text-muted-foreground">
              Approved Wordplay
            </span>
            {visibleApprovedPairs.length > 0 && (
              <Badge variant="secondary" className="text-[10px]">{visibleApprovedPairs.length}</Badge>
            )}
          </div>
          {loadingApproved && <Loader2 className="h-3.5 w-3.5 animate-spin text-muted-foreground" />}
        </div>
        {approvedError ? (
          <div className="flex items-start gap-1.5 px-4 pb-3 text-[10px] text-destructive" role="alert">
            <AlertCircle className="mt-0.5 h-3 w-3 shrink-0" />
            <span>承認済みワードプレイを取得できませんでした: {approvedError}</span>
          </div>
        ) : visibleApprovedPairs.length > 0 ? (
          <div className="max-h-48 space-y-2 overflow-y-auto px-3 pb-3">
            {visibleApprovedPairs.map((pair) => (
              <div key={pair.id} className="rounded-lg border bg-card p-3 shadow-sm">
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0">
                    <div className="flex items-center gap-2">
                      <Badge variant="outline" className="max-w-28 truncate text-[9px]">
                        {pair.keyword}
                      </Badge>
                      <span className="truncate text-xs font-bold" title={pair.to_track?.title}>
                        {pair.to_track?.title || `削除済みの曲（ID: ${pair.to_track_id}）`}
                      </span>
                    </div>
                    <p className="mt-1 truncate text-[10px] text-muted-foreground">
                      {pair.to_track?.artist || "ライブラリにありません"}
                    </p>
                    <div className="mt-2 flex flex-wrap items-center gap-1 text-[9px] text-muted-foreground">
                      <span className="rounded bg-muted px-1.5 py-0.5">
                        1 Cue “{pair.source_phrase || pair.keyword}”
                      </span>
                      <span aria-hidden="true">→</span>
                      <span className="rounded bg-muted px-1.5 py-0.5">
                        2 次曲イントロ
                      </span>
                      <span aria-hidden="true">→</span>
                      <span className="rounded bg-primary/10 px-1.5 py-0.5 text-primary">
                        3 着地 “{pair.target_phrase || pair.keyword}”
                      </span>
                    </div>
                  </div>
                  <div className="flex shrink-0 items-center gap-1">
                    {pair.to_track && (
                      <PlayButton
                        track={pair.to_track}
                        timestamp={pair.target_intro_timestamp ?? pair.target_landing_timestamp ?? pair.to_timestamp}
                        variant="ghost"
                        size="icon"
                        className="h-7 w-7"
                        iconClassName="h-3 w-3"
                        showPauseWhenPlaying
                      />
                    )}
                    <Button
                      size="sm"
                      className="h-7 px-2 text-[10px]"
                      disabled={!pair.to_track}
                      onClick={() => handleAddApproved(pair)}
                    >
                      <LinkIcon className="h-3 w-3" /> Connect
                    </Button>
                  </div>
                </div>
                {pair.transition_notes && (
                  <p className="mt-2 line-clamp-2 border-t pt-2 text-[10px] text-muted-foreground">
                    {pair.transition_notes}
                  </p>
                )}
              </div>
            ))}
          </div>
        ) : !loadingApproved ? (
          <p className="px-4 pb-3 text-[10px] text-muted-foreground">
            この曲から使える承認済みワードプレイはありません。
          </p>
        ) : null}
      </section>

      {/* Lyrics Display */}
      <div
        className={cn(
          "min-h-0 border-b relative bg-muted/5 transition-all duration-300 ease-in-out overflow-hidden",
          isLyricsExpanded
            ? "flex-[3] opacity-100"
            : "h-0 opacity-0 pointer-events-none"
        )}
      >
        <ScrollArea className="h-full">
          <div className="p-8 pb-16 font-serif max-w-2xl mx-auto">
            {loading ? (
              <div className="flex flex-col items-center justify-center py-24 gap-4 opacity-40">
                <Loader2 className="h-8 w-8 animate-spin" />
                <span className="text-[10px] uppercase tracking-widest">
                  Loading Lyrics
                </span>
              </div>
            ) : lyricsNotFound ? (
              <div className="flex flex-col items-center justify-center py-24 gap-3 text-muted-foreground">
                <MessageSquare className="h-10 w-10 opacity-20" />
                <p className="text-sm">この曲には歌詞がありません</p>
                <p className="text-xs opacity-60">
                  Tag Manager の「Auto-Fill Lyrics」で歌詞を自動取得できます
                </p>
              </div>
            ) : (
              renderedLyrics
            )}
          </div>
        </ScrollArea>
      </div>

      {/* Search Results / Matches */}
      <div className="flex-[2] min-h-0 flex flex-col bg-background">
        <div className="px-4 py-2 border-b flex gap-2 items-center shrink-0 bg-muted/20">
          <div className="flex items-center gap-2 shrink-0">
            <span className="text-[10px] font-black text-muted-foreground uppercase tracking-wider">
              Matched Connections
            </span>
            {activeKeyword && (
              <Badge className="bg-primary text-primary-foreground animate-in zoom-in-95 text-[10px]">
                {activeKeyword}
              </Badge>
            )}
          </div>
          <Input
            value={keywordInput}
            onChange={(event) => setKeywordInput(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") handleKeywordSearch(keywordInput);
            }}
            placeholder="Enter a lyric phrase (3+ characters)"
            className="h-8 text-xs"
          />
          <Button
            size="sm"
            variant="secondary"
            className="h-8 text-xs"
            onClick={() => handleKeywordSearch(keywordInput)}
            disabled={keywordInput.trim().length < 3 || searching}
          >
            Find links
          </Button>
          {searching && (
            <Loader2 className="h-3 w-3 animate-spin text-primary" />
          )}
        </div>

        <ScrollArea className="flex-1">
          <div className="p-4 space-y-3">
            {searchResults.length > 0 ? (
              searchResults.map((res, i) => (
                <div
                  key={i}
                  className="group border rounded-xl p-4 bg-card hover:border-primary/40 transition-all shadow-sm"
                >
                  <div className="flex justify-between items-start gap-3 mb-3">
                    <div className="min-w-0">
                      <div className="font-bold text-sm truncate leading-tight">
                        {res.track.title}
                      </div>
                      <div className="text-[10px] text-muted-foreground truncate mt-1">
                        {res.track.artist}
                      </div>
                    </div>
                    <div className="flex gap-1.5 shrink-0">
                      {res.timestamp !== null && (
                        <PlayButton
                          track={res.track}
                          timestamp={res.timestamp}
                          variant="secondary"
                          size="icon"
                          className="h-8 w-8 hover:text-green-500"
                          iconClassName="h-3.5 w-3.5 fill-current"
                        />
                      )}
                      <Button
                        size="sm"
                        variant="default"
                        className="h-8 text-xs gap-1.5 px-4 font-bold"
                        onClick={() =>
                          handleAddWithMeta(
                            res.track,
                            res.matched_text,
                            res.timestamp
                          )
                        }
                      >
                        <LinkIcon className="h-3.5 w-3.5" /> Connect
                      </Button>
                    </div>
                  </div>

                  <div className="text-[11px] bg-muted/40 p-3 rounded-lg border-l-4 border-primary/20 italic text-muted-foreground/80 leading-relaxed font-serif">
                    {res.snippet.map((line: string, j: number) => (
                      <div
                        key={j}
                        className={cn(
                          "truncate",
                          line
                            .toLowerCase()
                            .includes(activeKeyword?.toLowerCase() || "") &&
                            "text-foreground font-bold not-italic"
                        )}
                      >
                        {line}
                      </div>
                    ))}
                  </div>
                </div>
              ))
            ) : activeKeyword && !searching ? (
              <div className="text-center py-16 text-muted-foreground text-xs italic opacity-60">
                No matching lyrics found in the library.
              </div>
            ) : (
              !activeKeyword && (
                <div className="text-center py-20 text-muted-foreground/30 text-[10px] flex flex-col items-center gap-4 uppercase font-black">
                  <LinkIcon className="h-8 w-8 opacity-20" />
                  Select a keyword to find connections
                </div>
              )
            )}
          </div>
        </ScrollArea>
      </div>
    </div>
  );
}
