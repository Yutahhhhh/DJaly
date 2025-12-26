import { useState, useEffect } from "react";
import { Track } from "@/types";
import { lyricsService, AnalysisResult } from "@/services/lyrics";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Badge } from "@/components/ui/badge";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Loader2, Search, Link as LinkIcon, ChevronDown, ChevronUp, Sparkles } from "lucide-react";
import { cn } from "@/lib/utils";

interface WordTabProps {
  sourceTrack: Track | null;
  onAddTrack: (track: Track, wordplayData?: any) => void;
}

// API response type (matches backend)
interface LyricSnippet {
  track: Track;
  snippet: string[];
  match_line: number;
}

export function WordTab({ sourceTrack, onAddTrack }: WordTabProps) {
  const [lyrics, setLyrics] = useState<string[]>([]);
  const [analysis, setAnalysis] = useState<AnalysisResult>({ words: [], phrases: [] });
  const [searchQuery, setSearchQuery] = useState("");
  const [searchResults, setSearchResults] = useState<LyricSnippet[]>([]);
  const [loadingLyrics, setLoadingLyrics] = useState(false);
  const [loadingAnalysis, setLoadingAnalysis] = useState(false);
  const [loadingSearch, setLoadingSearch] = useState(false);
  const [selectedSourceLine, setSelectedSourceLine] = useState<string | null>(null);
  const [isLyricsExpanded, setIsLyricsExpanded] = useState(false);
  const [activeTab, setActiveTab] = useState("words");

  useEffect(() => {
    if (sourceTrack) {
      fetchLyrics(sourceTrack.id);
      fetchAnalysis(sourceTrack.id);
      setIsLyricsExpanded(false); 
    } else {
      setLyrics([]);
      setAnalysis({ words: [], phrases: [] });
    }
  }, [sourceTrack]);

  const fetchLyrics = async (trackId: number) => {
    setLoadingLyrics(true);
    try {
      const data = await lyricsService.getLyrics(trackId);
      if (data && data.content) {
        setLyrics(data.content.split("\n"));
      } else {
        setLyrics(["No lyrics found."]);
      }
    } catch (error) {
      console.error("Failed to fetch lyrics", error);
      setLyrics(["Failed to load lyrics."]);
    } finally {
      setLoadingLyrics(false);
    }
  };

  const fetchAnalysis = async (trackId: number) => {
    setLoadingAnalysis(true);
    setAnalysis({ words: [], phrases: [] });
    try {
      const data = await lyricsService.analyzeLyrics(trackId);
      setAnalysis(data);
    } catch (error) {
      console.error("Failed to analyze lyrics", error);
    } finally {
      setLoadingAnalysis(false);
    }
  };

  const handleSearch = async () => {
    if (!searchQuery) return;
    setLoadingSearch(true);
    try {
      const excludeId = sourceTrack?.id;
      const data = await lyricsService.searchLyrics(searchQuery, excludeId);
      setSearchResults(data);
    } catch (error) {
      console.error("Search failed", error);
    } finally {
      setLoadingSearch(false);
    }
  };

  const handleLineClick = (line: string) => {
    setSelectedSourceLine(line);
    setSearchQuery(line);
    setIsLyricsExpanded(false); 
  };
  
  const handleKeywordClick = (keyword: string) => {
      setSearchQuery(keyword);
  };

  useEffect(() => {
      if (searchQuery && searchQuery.length > 2) {
          const timer = setTimeout(() => {
              handleSearch();
          }, 500);
          return () => clearTimeout(timer);
      }
  }, [searchQuery]);

  const getLineMatchInfo = (line: string) => {
      if (!analysis.words.length && !analysis.phrases.length) return null;
      
      // Check both words and phrases
      const wordMatches = analysis.words.filter(k => line.toLowerCase().includes(k.keyword.toLowerCase()));
      const phraseMatches = analysis.phrases.filter(k => line.toLowerCase().includes(k.keyword.toLowerCase()));
      
      const allMatches = [...wordMatches, ...phraseMatches];
      if (allMatches.length === 0) return null;
      return allMatches;
  };

  return (
    <div className="flex flex-col h-full w-full overflow-hidden">
      {/* Top Section: Source Lyrics (Expandable) */}
      <div className="flex-none border-b bg-muted/10">
        <div 
            className="p-3 flex items-center justify-between cursor-pointer hover:bg-muted/20 transition-colors"
            onClick={() => setIsLyricsExpanded(!isLyricsExpanded)}
        >
            <div className="flex flex-col overflow-hidden">
                <span className="font-medium text-sm truncate">
                    {sourceTrack ? `Source: ${sourceTrack.title}` : "Select a track"}
                </span>
                {selectedSourceLine ? (
                    <span className="text-xs text-primary truncate mt-0.5">Selected: "{selectedSourceLine}"</span>
                ) : (
                    <span className="text-xs text-muted-foreground mt-0.5">Click to select phrase...</span>
                )}
            </div>
            <Button variant="ghost" size="sm" className="h-8 w-8 p-0 shrink-0 ml-2">
                {isLyricsExpanded ? <ChevronUp className="h-4 w-4"/> : <ChevronDown className="h-4 w-4"/>}
            </Button>
        </div>

        {isLyricsExpanded && (
            <div className="h-64 border-t animate-in slide-in-from-top-2 duration-200">
                <ScrollArea className="h-full p-4">
                {loadingLyrics ? (
                    <div className="flex justify-center p-4"><Loader2 className="animate-spin" /></div>
                ) : (
                    <div className="space-y-1">
                    {lyrics.map((line, i) => {
                        const matchInfo = getLineMatchInfo(line);
                        return (
                            <div
                                key={i}
                                onClick={(e) => { e.stopPropagation(); handleLineClick(line); }}
                                className={cn(
                                    "p-1.5 rounded cursor-pointer text-sm hover:bg-accent hover:text-accent-foreground transition-colors flex justify-between items-center gap-2",
                                    selectedSourceLine === line && "bg-primary/20 font-medium text-primary"
                                )}
                            >
                                <span className="truncate">{line}</span>
                                {matchInfo && (
                                    <span className="text-[10px] bg-primary/10 text-primary px-1.5 py-0.5 rounded-full shrink-0 whitespace-nowrap">
                                        {matchInfo.reduce((acc, curr) => acc + curr.count, 0)} matches
                                    </span>
                                )}
                            </div>
                        );
                    })}
                    </div>
                )}
                </ScrollArea>
            </div>
        )}
      </div>

      {/* Bottom Section: Search & Results */}
      <div className="flex-1 flex flex-col min-h-0 bg-background">
        <div className="p-3 border-b space-y-3 flex-none">
          <div className="relative">
            <Search className="absolute left-2 top-2.5 h-4 w-4 text-muted-foreground" />
            <Input
              placeholder="Search lyrics or keywords..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="pl-8"
            />
          </div>
          
          {/* Keywords Tabs */}
          {loadingAnalysis ? (
             <div className="flex items-center gap-2 text-xs text-muted-foreground py-2">
                 <Loader2 className="h-3 w-3 animate-spin" /> Analyzing lyrics with AI...
             </div>
          ) : (analysis.words.length > 0 || analysis.phrases.length > 0) && (
            <Tabs defaultValue="words" value={activeTab} onValueChange={setActiveTab} className="w-full">
                <TabsList className="grid w-full grid-cols-2 h-8">
                    <TabsTrigger value="words" className="text-xs">Words ({analysis.words.length})</TabsTrigger>
                    <TabsTrigger value="phrases" className="text-xs">Phrases ({analysis.phrases.length})</TabsTrigger>
                </TabsList>
                <TabsContent value="words" className="mt-2">
                    <ScrollArea className="h-24 w-full rounded-md border p-2">
                        <div className="flex flex-wrap gap-1">
                        {analysis.words.map((item, i) => (
                            <Badge 
                                key={i} 
                                variant="secondary" 
                                className="cursor-pointer hover:bg-primary hover:text-primary-foreground transition-colors flex gap-1 items-center text-[10px] px-1.5 h-5"
                                onClick={() => handleKeywordClick(item.keyword)}
                            >
                            {item.keyword}
                            <span className="bg-background/50 px-1 rounded text-[9px] min-w-[0.8rem] text-center">{item.count}</span>
                            </Badge>
                        ))}
                        </div>
                    </ScrollArea>
                </TabsContent>
                <TabsContent value="phrases" className="mt-2">
                    <ScrollArea className="h-24 w-full rounded-md border p-2">
                        <div className="flex flex-wrap gap-1">
                        {analysis.phrases.map((item, i) => (
                            <Badge 
                                key={i} 
                                variant="outline" 
                                className="cursor-pointer hover:bg-primary hover:text-primary-foreground transition-colors flex gap-1 items-center text-[10px] px-1.5 h-5 border-primary/30"
                                onClick={() => handleKeywordClick(item.keyword)}
                            >
                            <Sparkles className="h-2 w-2 mr-0.5 text-yellow-500" />
                            {item.keyword}
                            <span className="bg-muted px-1 rounded text-[9px] min-w-[0.8rem] text-center">{item.count}</span>
                            </Badge>
                        ))}
                        </div>
                    </ScrollArea>
                </TabsContent>
            </Tabs>
          )}
        </div>

        <ScrollArea className="flex-1 p-3">
          {loadingSearch ? (
             <div className="flex justify-center p-4"><Loader2 className="animate-spin" /></div>
          ) : (
            <div className="space-y-3">
              {searchResults.map((result, i) => (
                <div key={i} className="border rounded-md p-3 space-y-2 hover:border-primary/50 transition-colors bg-card">
                  <div className="flex justify-between items-start gap-2">
                    <div className="min-w-0">
                      <div className="font-medium text-sm truncate">{result.track.title}</div>
                      <div className="text-xs text-muted-foreground truncate">{result.track.artist}</div>
                    </div>
                    <Button 
                        size="sm" 
                        variant="outline" 
                        className="h-7 text-xs gap-1 shrink-0"
                        onClick={() => onAddTrack(result.track, {
                            source_phrase: selectedSourceLine || "",
                            target_phrase: result.snippet[1] || "", 
                            keyword: searchQuery
                        })}
                    >
                        <LinkIcon className="h-3 w-3" /> Connect
                    </Button>
                  </div>
                  
                  <div className="text-xs bg-muted/30 p-2 rounded italic text-muted-foreground">
                    {result.snippet.map((line, j) => (
                        <div key={j} className={cn("truncate", line.toLowerCase().includes(searchQuery.toLowerCase()) && "text-foreground font-medium")}>
                            {line}
                        </div>
                    ))}
                  </div>
                </div>
              ))}
              {searchResults.length === 0 && searchQuery && !loadingSearch && (
                  <div className="text-center text-muted-foreground text-sm py-8">No matches found</div>
              )}
            </div>
          )}
        </ScrollArea>
      </div>
    </div>
  );
}
