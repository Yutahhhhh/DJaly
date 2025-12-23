import { useState, useEffect } from "react";
import { Sidebar } from "@/components/sidebar";
import { MusicLibrary } from "@/components/music-library";
import { PromptManager } from "@/components/prompt-manager";
import { SettingsView } from "@/components/settings-view";
import { FileExplorer } from "@/components/file-explorer";
import { SetlistCreator } from "@/components/setlist-creator";
import { GenreManager } from "@/components/genre-manager/GenreManager";
import { MusicPlayer } from "@/components/MusicPlayer";
import { GlobalProgressIndicator } from "@/components/GlobalProgressIndicator";
import { IngestionProvider } from "@/contexts/IngestionContext";
import { Track } from "@/types";
import { DashboardView } from "@/components/dashboard/DashboardView";
import { API_BASE_URL } from "@/services/api-client";
import { LoadingScreen } from "@/components/LoadingScreen";
import { Updater } from "@/components/Updater";

function App() {
  const [activeView, setActiveView] = useState("dashboard");
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [isServerReady, setIsServerReady] = useState(false);

  // Music Player State
  const [currentTrack, setCurrentTrack] = useState<Track | null>(null);
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
            onPlay={(track) => setCurrentTrack(track)}
            currentTrackId={currentTrack?.id}
            isPlayerLoading={isPlayerLoading}
          />
        );
      case "setlists":
        return (
          <SetlistCreator
            onPlay={(track) => setCurrentTrack(track)}
            currentTrackId={currentTrack?.id}
          />
        );
      case "explorer":
        return <FileExplorer />;
      case "prompts":
        return <PromptManager />;
      case "genres":
        return <GenreManager onPlay={(track) => setCurrentTrack(track)} />;
      case "settings":
        return <SettingsView />;
      default:
        return <DashboardView onNavigate={setActiveView} />;
    }
  };

  return (
    <IngestionProvider>
      <Updater />
      <div className="h-screen w-full bg-background text-foreground flex overflow-hidden">
        <Sidebar
          activeView={activeView}
          onNavigate={setActiveView}
          isOpen={sidebarOpen}
          toggleSidebar={() => setSidebarOpen(!sidebarOpen)}
        />
        <main className="flex-1 overflow-hidden relative flex flex-col">
          <div className="flex-1 overflow-hidden relative">{renderView()}</div>

          {/* Spacer for Music Player when active to prevent content overlap */}
          {currentTrack && <div className="h-24 shrink-0" />}
        </main>

        {/* Global Components */}
        <GlobalProgressIndicator />

        <MusicPlayer
          track={currentTrack}
          onClose={() => setCurrentTrack(null)}
          onLoadingChange={setIsPlayerLoading}
        />
      </div>
    </IngestionProvider>
  );
}

export default App;
