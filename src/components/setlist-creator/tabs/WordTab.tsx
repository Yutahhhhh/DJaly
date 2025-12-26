import { useState, useEffect, useMemo } from "react";
import { Track } from "@/types";
import { lyricsService } from "@/services/lyrics";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Badge } from "@/components/ui/badge";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import {
  Loader2,
  Link as LinkIcon,
  Music,
  MessageSquare,
  ChevronDown,
  ChevronUp,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { usePlayerStore } from "@/stores/playerStore";
import { PlayButton } from "@/components/ui/PlayButton";
import { normalizeLyricsTimeTags } from "@/lib/utils";

interface WordTabProps {
  sourceTrack: Track | null;
  onAddTrack: (track: Track, wordplayData?: any) => void;
}

interface KeywordMatch {
  keyword: string;
  count: number;
}

export function WordTab({ sourceTrack, onAddTrack }: WordTabProps) {
  const [lyricsText, setLyricsText] = useState("");
  const [keywords, setKeywords] = useState<KeywordMatch[]>([]);
  const [searchResults, setSearchResults] = useState<any[]>([]);

  const [loading, setLoading] = useState(false);
  const [searching, setSearching] = useState(false);
  const [activeKeyword, setActiveKeyword] = useState<string | null>(null);
  const [isLyricsExpanded, setIsLyricsExpanded] = useState(true);

  const { playAt, currentTrack, isPlaying } = usePlayerStore();

  // activeKeywordの最初のタイムスタンプを取得
  const firstKeywordTimestamp = useMemo(() => {
    if (!activeKeyword || !lyricsText) return null;

    const lines = lyricsText.split("\n");
    for (const line of lines) {
      const timestampMatch = line.match(/\[(\d+):(\d+(?:\.\d+)?)\]/);
      const cleanLine = line.replace(/\[.*\]/, "").trim();
      
      if (cleanLine.toLowerCase().includes(activeKeyword.toLowerCase()) && timestampMatch) {
        return parseInt(timestampMatch[1]) * 60 + parseFloat(timestampMatch[2]);
      }
    }
    return null;
  }, [activeKeyword, lyricsText]);

  // データ取得
  useEffect(() => {
    if (!sourceTrack) return;

    const load = async () => {
      setLoading(true);
      setSearchResults([]);
      setActiveKeyword(null);
      try {
        const [lyData, kwData] = await Promise.all([
          lyricsService.getLyrics(sourceTrack.id),
          lyricsService.analyzeLyrics(sourceTrack.id),
        ]);
        setLyricsText(normalizeLyricsTimeTags(lyData.content || ""));
        setKeywords(Array.isArray(kwData) ? kwData : []);
      } catch (error) {
        console.error("Failed to load wordplay data", error);
      } finally {
        setLoading(false);
      }
    };
    load();
  }, [sourceTrack?.id]);

  // 検索実行
  const handleKeywordSearch = async (kw: string) => {
    setActiveKeyword(kw);
    setSearching(true);
    try {
      const results = await lyricsService.searchLyrics(kw, sourceTrack?.id);
      console.log("[WordTab] Search results for keyword:", kw, results);
      setSearchResults(results);
    } catch (error) {
      console.error("Search failed", error);
    } finally {
      setSearching(false);
    }
  };

  const renderedLyrics = useMemo(() => {
    if (!lyricsText) return null;

    const lines = lyricsText.split("\n");
    return lines.map((line, lineIdx) => {
      const timestampMatch = line.match(/\[(\d+):(\d+(?:\.\d+)?)\]/);
      const timestamp = timestampMatch
        ? parseInt(timestampMatch[1]) * 60 + parseFloat(timestampMatch[2])
        : null;
      const cleanLine = line.replace(/\[.*\]/, "").trim();

      if (!cleanLine) return <div key={lineIdx} className="h-4" />;

      const lineKeywords = Array.isArray(keywords)
        ? keywords.filter((k) =>
            cleanLine.toLowerCase().includes(k.keyword.toLowerCase())
          )
        : [];

      return (
        <div
          key={lineIdx}
          className="group/line flex items-start gap-2 py-1 hover:bg-muted/30 rounded px-2 transition-colors"
        >
          <div className="flex-1 text-sm leading-relaxed">
            {lineKeywords.length > 0 ? (
              <Popover>
                <PopoverTrigger asChild>
                  <span className="cursor-pointer border-b border-dashed border-primary/60 hover:text-primary transition-colors">
                    {cleanLine}
                  </span>
                </PopoverTrigger>
                <PopoverContent
                  className="w-56 p-2 shadow-2xl z-60"
                  side="top"
                  align="start"
                >
                  <div className="text-[10px] font-bold text-muted-foreground mb-2 uppercase">
                    Keyword Search:
                  </div>
                  <div className="flex flex-wrap gap-1">
                    {lineKeywords.map((k, ki) => (
                      <Badge
                        key={ki}
                        variant={
                          activeKeyword === k.keyword ? "default" : "secondary"
                        }
                        className="cursor-pointer hover:bg-primary hover:text-primary-foreground text-[11px]"
                        onClick={() => handleKeywordSearch(k.keyword)}
                      >
                        {k.keyword} ({k.count})
                      </Badge>
                    ))}
                  </div>
                  {timestamp !== null && (
                    <div className="mt-2 pt-2 border-t flex justify-end">
                      <PlayButton
                        track={sourceTrack!}
                        timestamp={timestamp}
                        variant="ghost"
                        size="sm"
                        className="h-7 text-[10px] gap-1 px-2 hover:text-green-500 font-bold"
                        iconClassName="h-3 w-3 fill-current"
                      >
                        Preview (3s before)
                      </PlayButton>
                    </div>
                  )}
                </PopoverContent>
              </Popover>
            ) : (
              <span className="text-muted-foreground/70">{cleanLine}</span>
            )}
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
  }, [lyricsText, keywords, activeKeyword, sourceTrack, playAt]);

  if (!sourceTrack) {
    return (
      <div className="flex-1 flex flex-col items-center justify-center text-muted-foreground p-10 text-center gap-4">
        <MessageSquare className="h-12 w-12 opacity-20" />
        <p className="text-sm italic">Select a track to start analysis.</p>
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full bg-background overflow-hidden">
      {/* Header: 曲名・再生ボタン・展開制御 */}
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
            {/* From再生ボタン */}
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

      {/* 歌詞エリア */}
      <div
        className={cn(
          "min-h-0 border-b relative bg-muted/5 transition-all duration-300 ease-in-out overflow-hidden",
          isLyricsExpanded
            ? "flex-3 opacity-100"
            : "h-0 opacity-0 pointer-events-none"
        )}
      >
        <ScrollArea className="h-full">
          <div className="p-8 pb-16 font-serif max-w-2xl mx-auto">
            {loading ? (
              <div className="flex flex-col items-center justify-center py-24 gap-4 opacity-40">
                <Loader2 className="h-8 w-8 animate-spin" />
                <span className="text-[10px] uppercase tracking-widest">
                  Analyzing
                </span>
              </div>
            ) : (
              renderedLyrics
            )}
          </div>
        </ScrollArea>
      </div>

      {/* 接続先検索結果 */}
      <div className="flex-2 min-h-0 flex flex-col bg-background">
        <div className="px-4 py-2 border-b flex justify-between items-center shrink-0 bg-muted/20">
          <div className="flex items-center gap-2">
            <span className="text-[10px] font-black text-muted-foreground uppercase">
              Matched Links
            </span>
            {activeKeyword && (
              <Badge className="bg-primary text-primary-foreground animate-in zoom-in-95 text-[10px]">
                {activeKeyword}
              </Badge>
            )}
          </div>
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
                          onAddTrack(res.track, {
                            source_phrase: activeKeyword || "",
                            target_phrase: res.matched_text,
                            keyword: activeKeyword,
                          })
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
                No links found.
              </div>
            ) : (
              !activeKeyword && (
                <div className="text-center py-20 text-muted-foreground/30 text-[10px] flex flex-col items-center gap-4 uppercase font-black">
                  <LinkIcon className="h-8 w-8 opacity-20" />
                  Select a keyword in the lyrics
                </div>
              )
            )}
          </div>
        </ScrollArea>
      </div>
    </div>
  );
}
