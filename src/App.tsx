import { useState, useEffect, useRef } from "react";
import { Sidebar } from "@/components/sidebar";
import { MusicLibrary } from "@/components/music-library";
import { SettingsView } from "@/components/settings-view";
import { McpView } from "@/components/mcp-view/McpView";
import { FileExplorer } from "@/components/file-explorer";
import { SetlistCreator } from "@/components/setlist-creator";
import { TagManager } from "@/components/tag-manager/TagManager";
import { MusicPlayer } from "@/components/MusicPlayer";
import { GlobalProgressIndicator } from "@/components/GlobalProgressIndicator";
import { IngestionProvider } from "@/contexts/IngestionContext";
import { MetadataProvider } from "@/contexts/MetadataContext";
import { DashboardView } from "@/components/dashboard/DashboardView";
import { API_BASE_URL } from "@/services/api-client";
import { LoadingScreen } from "@/components/LoadingScreen";
import { Updater } from "@/components/Updater";
import { Toaster } from "@/components/ui/toast";
import { usePlayerStore } from "@/stores/playerStore";
import { WordplayView } from "@/components/wordplay";
import { djEngineClient } from "@/services/dj-engine/client";
import { DECK_IDS } from "@/types/dj-engine";
import { ModeToggle, PlayWorkspace, type AppMode } from "@/components/play";

function App() {
  const [appMode, setAppMode] = useState<AppMode>(() => sessionStorage.getItem("djaly.appMode") === "play" ? "play" : "analysis");
  const [activeView, setActiveView] = useState(() =>
    sessionStorage.getItem("djaly.activeView") ?? "dashboard"
  );
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [isServerReady, setIsServerReady] = useState(false);
  const previousMode = useRef(appMode);
  const [releasingPerformanceAudio, setReleasingPerformanceAudio] = useState(false);

  // Music Player State
  const { currentTrack, pause } = usePlayerStore();
  const [isPlayerLoading, setIsPlayerLoading] = useState(false);

  // Server Health Check
  useEffect(() => {
    const checkServer = async () => {
      try {
        const baseUrl = API_BASE_URL.replace('/api', '');
        console.log("Checking server at:", baseUrl);
        const res = await fetch(baseUrl);
        if (res.ok) {
          setIsServerReady(true);
        } else {
          throw new Error("Server not ready");
        }
      } catch (e) {
        // リトライ
        setTimeout(checkServer, 1000);
      }
    };
    checkServer();
  }, []);

  // Performance mode owns audio output. Stop the browser preview path before
  // entering it so gain/EQ are never applied to two independent players.
  useEffect(() => {
    sessionStorage.setItem("djaly.activeView", activeView);
    if (appMode === "play") {
      pause();
      setReleasingPerformanceAudio(false);
    }
    if (previousMode.current === "play" && appMode === "analysis") {
      // Deliberate navigation away is an audio-safety boundary. A full webview
      // reload still leaves the native process playing and reconnectable.
      setReleasingPerformanceAudio(true);
      const hasSession = Boolean(djEngineClient.getSessionId());
      const releaseRecording = hasSession && djEngineClient.getState().snapshot?.recording?.active
        ? djEngineClient.stopRecording()
        : Promise.resolve();
      void releaseRecording.catch(() => undefined).then(() => hasSession
        ? Promise.allSettled(DECK_IDS.map((deck) => djEngineClient.pause(deck)))
        : djEngineClient.stop().then(() => []))
        .then(async (outcomes) => {
          if (outcomes.some((outcome) => outcome.status === "rejected")) {
            await djEngineClient.stop();
          }
          setReleasingPerformanceAudio(false);
        })
        .catch((failure) => {
          console.error("Native DJ audio could not be released; browser player remains disabled", failure);
        });
    }
    previousMode.current = appMode;
    sessionStorage.setItem("djaly.appMode", appMode);
  }, [activeView, appMode, pause]);

  if (!isServerReady) {
    return <LoadingScreen />;
  }

  const renderView = () => {
    switch (activeView) {
      case "dashboard":
        return <DashboardView onNavigate={setActiveView} />;
      case "library":
        return (
          <MusicLibrary
            isPlayerLoading={isPlayerLoading}
          />
        );
      case "setlists":
        return (
          <SetlistCreator />
        );
      case "explorer":
        return <FileExplorer />;
      case "tags":
        return <TagManager />;
      case "mcp":
        return <McpView />;
      case "wordplay":
        return <WordplayView />;
      case "settings":
        return <SettingsView />;
      default:
        return <DashboardView onNavigate={setActiveView} />;
    }
  };

  return (
    <IngestionProvider>
      <MetadataProvider>
        <Updater />
        <div className="flex h-screen min-h-0 flex-col overflow-hidden bg-[#080b11]">
          <div className="z-[80] flex h-10 shrink-0 items-center border-b border-slate-700 bg-[#11151d] px-3 shadow-md">
            <span className="text-[10px] font-bold uppercase tracking-[0.22em] text-slate-500">Djaly Workspace</span>
            <div className="ml-auto"><ModeToggle mode={appMode} onChange={(mode) => { if (appMode === "play" && mode === "analysis") setReleasingPerformanceAudio(true); setAppMode(mode); }} /></div>
          </div>
        <div className="min-h-0 flex-1">
        {appMode === "play" ? <PlayWorkspace /> : <div className="h-full w-full bg-background text-foreground flex overflow-hidden">
        <Sidebar
          activeView={activeView}
          onNavigate={setActiveView}
          isOpen={sidebarOpen}
          toggleSidebar={() => setSidebarOpen(!sidebarOpen)}
        />
        <main className="flex-1 overflow-hidden relative flex flex-col">
          <div className="flex-1 overflow-hidden relative">{renderView()}</div>

          {/* Spacer for Music Player when active to prevent content overlap */}
          {currentTrack && !releasingPerformanceAudio && <div className="h-24 shrink-0" />}
        </main>

        {/* Global Components */}
        <GlobalProgressIndicator />

        {!releasingPerformanceAudio && (
          <MusicPlayer onLoadingChange={setIsPlayerLoading} />
        )}
        <Toaster />
      </div>}
        </div>
        </div>
      </MetadataProvider>
    </IngestionProvider>
  );
}

export default App;
