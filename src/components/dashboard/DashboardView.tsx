import { useEffect, useState } from "react";
import { systemService, DashboardStats, SystemHealth } from "@/services/system";
import { StatCards } from "./StatCards";
import { GenreBarChart } from "./GenreBarChart";
import { RecentSetlists } from "./RecentSetlists";
import { Button } from "@/components/ui/button";
import { Loader2, RefreshCw, AlertTriangle } from "lucide-react";
import { useIngestion } from "@/contexts/IngestionContext";
import { AnalysisModal } from "@/components/file-explorer/AnalysisModal";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";

interface DashboardViewProps {
  onNavigate: (view: string) => void;
}

export function DashboardView({ onNavigate }: DashboardViewProps) {
  const [stats, setStats] = useState<DashboardStats | null>(null);
  const [health, setHealth] = useState<SystemHealth | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Ingestion Control
  const [isAnalysisModalOpen, setIsAnalysisModalOpen] = useState(false);
  const [forceUpdate, setForceUpdate] = useState(false);
  const { isAnalyzing } = useIngestion();

  // Load Data
  const fetchData = async () => {
    setIsLoading(true);
    setError(null);
    try {
      const [statsData, healthData] = await Promise.all([
        systemService.getDashboardStats(),
        systemService.getHealth(),
      ]);
      setStats(statsData);
      setHealth(healthData);
    } catch (e: any) {
      console.error("Failed to load dashboard data", e);
      setError(e.message || "Failed to load dashboard data");
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    fetchData();
  }, [isAnalyzing]); // Refresh when analysis status changes

  if (isLoading && !stats) {
    return (
      <div className="h-full flex items-center justify-center">
        <div className="flex flex-col items-center gap-2 text-muted-foreground">
          <Loader2 className="h-8 w-8 animate-spin" />
          <p>Loading Dashboard...</p>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="h-full flex items-center justify-center p-4">
        <div className="text-center space-y-4">
          <h2 className="text-xl font-bold text-destructive">
            Dashboard Error
          </h2>
          <p className="text-muted-foreground">{error}</p>
          <Button onClick={fetchData}>Try Again</Button>
        </div>
      </div>
    );
  }

  if (!stats) return null;

  return (
    <div className="h-full flex flex-col p-6 space-y-6 overflow-y-auto">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Dashboard</h1>
          <p className="text-muted-foreground">
            Overview of your music library and system status.
          </p>
        </div>
        <div className="flex items-center gap-2">
          {health?.ollama_status &&
            !health.ollama_status.includes("Connected") && (
              <span className="text-xs text-red-500 font-medium px-2 py-1 bg-red-50 rounded border border-red-100">
                LLM Connection Error
              </span>
            )}
          <Button
            variant="outline"
            size="sm"
            onClick={fetchData}
            disabled={isLoading}
          >
            <RefreshCw
              className={`h-4 w-4 mr-2 ${isLoading ? "animate-spin" : ""}`}
            />
            Refresh
          </Button>
        </div>
      </div>

      {/* Alerts */}
      {!stats.config.has_root_path && (
        <Alert variant="destructive">
          <AlertTriangle className="h-4 w-4" />
          <AlertTitle>Root Path Not Configured</AlertTitle>
          <AlertDescription className="flex items-center justify-between">
            <span>
              Please set your music folder location in Settings to start using
              Djaly.
            </span>
            <Button
              variant="outline"
              size="sm"
              className="bg-white text-destructive hover:bg-white/90"
              onClick={() => onNavigate("settings")}
            >
              Go to Settings
            </Button>
          </AlertDescription>
        </Alert>
      )}

      {/* KPI Cards */}
      <StatCards
        stats={stats}
        health={health} // ★ Added: 実際の接続状態を渡す
        onNavigate={onNavigate}
        onAnalyze={() => setIsAnalysisModalOpen(true)}
      />

      {/* Main Charts Area */}
      <div className="h-[400px]">
        <GenreBarChart data={stats.genre_distribution} />
      </div>

      {/* Bottom Section */}
      <div className="grid gap-4 md:grid-cols-2 h-[300px]">
        <RecentSetlists
          setlists={stats.recent_setlists}
          onNavigate={onNavigate}
        />

        {/* Quick Actions / Tips Placeholder */}
        <div className="border rounded-xl bg-card p-6 flex flex-col justify-center items-center text-center space-y-4 shadow-sm">
          <h3 className="font-semibold text-lg">Ready to Create?</h3>
          <p className="text-sm text-muted-foreground max-w-xs">
            Start building your next setlist using AI-powered recommendations
            and vibe matching.
          </p>
          <Button
            onClick={() => onNavigate("setlists")}
            className="w-full max-w-xs"
          >
            Create Setlist
          </Button>
          <Button
            variant="outline"
            onClick={() => onNavigate("library")}
            className="w-full max-w-xs"
          >
            Browse Library
          </Button>
        </div>
      </div>

      {/* Analysis Modal */}
      <AnalysisModal
        isOpen={isAnalysisModalOpen}
        onOpenChange={setIsAnalysisModalOpen}
        selectedPaths={new Set()}
        forceUpdate={forceUpdate}
        onSetForceUpdate={setForceUpdate}
        onToggleSelection={() => {}}
        onClearSelection={() => {}}
        onIngest={async () => {
          // Redirect to Explorer for Analysis if root is set
          onNavigate("explorer");
          setIsAnalysisModalOpen(false);
        }}
      />
    </div>
  );
}
