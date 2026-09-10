import { useState, useEffect } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  CardDescription,
} from "@/components/ui/card";
import { Separator } from "@/components/ui/separator";
import {
  Settings as SettingsIcon,
  AlertCircle,
  FileSpreadsheet,
  Bot,
  Globe,
} from "lucide-react";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  settingsService,
  LibraryAnalysisResult,
  MetadataAnalysisResult,
} from "@/services/settings";
import { ImportSection } from "./ImportSection";
import { LibraryImportDialog } from "./LibraryImportDialog";
import { MetadataImportDialog } from "./MetadataImportDialog";
import { useTheme } from "@/components/theme-provider";
import { downloadFile } from "@/lib/download";

export function SettingsView() {
  const { theme, setTheme } = useTheme();
  const [settings, setSettings] = useState<{ [key: string]: string }>({});
  const [status, setStatus] = useState<string>("");
  const [isError, setIsError] = useState(false);

  // Import State
  const [importModalOpen, setImportModalOpen] = useState(false);
  const [isAnalyzing, setIsAnalyzing] = useState(false);
  const [analysisResult, setAnalysisResult] = useState<LibraryAnalysisResult | null>(
    null
  );
  const [isImporting, setIsImporting] = useState(false);

  // Metadata Import State
  const [metadataModalOpen, setMetadataModalOpen] = useState(false);
  const [metadataAnalysis, setMetadataAnalysis] =
    useState<MetadataAnalysisResult | null>(null);

  // Export State
  const [exportingSectionId, setExportingSectionId] = useState<string | null>(null);

  useEffect(() => {
    fetchSettings();
  }, []);

  const fetchSettings = async () => {
    try {
      const data = await settingsService.getAll();
      setSettings(data);
    } catch (e: any) {
      console.error("Failed to fetch settings", e);
      setStatus(`Connection Error: ${e.message}`);
      setIsError(true);
    }
  };

  const saveSetting = async (key: string, value: string) => {
    setStatus("Saving...");
    setIsError(false);
    try {
      await settingsService.save(key, value);
      setSettings((prev) => ({ ...prev, [key]: value }));
      setStatus(`Saved ${key}`);
      setTimeout(() => setStatus(""), 2000);
    } catch (e: any) {
      console.error("Failed to save setting", e);
      setStatus(`Error: ${e.message}`);
      setIsError(true);
    }
  };

  const handleAnalyze = async (file: File, type: 'library' | 'metadata') => {
    setIsAnalyzing(true);
    if (type === 'library') { setImportModalOpen(true); setAnalysisResult(null); }
    if (type === 'metadata') { setMetadataModalOpen(true); setMetadataAnalysis(null); }

    try {
      const result = await settingsService.analyzeImport(file, type);
      if (type === 'library') setAnalysisResult(result as LibraryAnalysisResult);
      if (type === 'metadata') setMetadataAnalysis(result as MetadataAnalysisResult);
    } catch (error: any) {
      console.error(error);
      if (type === 'library') setImportModalOpen(false);
      if (type === 'metadata') setMetadataModalOpen(false);

      setStatus(`${type} Analysis Failed: ${error.message}`);
      setIsError(true);
    } finally {
      setIsAnalyzing(false);
    }
  };

  const handleExecuteImport = async () => {
    if (!analysisResult) return;
    setIsImporting(true);

    try {
      const payload = {
        new_tracks: analysisResult.new_tracks,
        path_updates: analysisResult.path_updates,
      };

      const data = await settingsService.executeImport(payload, 'library');

      setStatus(data.message);
      setIsError(false);
      setImportModalOpen(false);
    } catch (error: any) {
      console.error(error);
      setStatus(`Import Failed: ${error.message}`);
      setIsError(true);
    } finally {
      setIsImporting(false);
    }
  };

  const handleExecuteMetadataImport = async () => {
    if (!metadataAnalysis) return;
    setIsImporting(true);

    try {
      const payload = {
        updates: metadataAnalysis.updates,
      };

      const data = await settingsService.executeImport(payload, 'metadata');

      setStatus(data.message);
      setIsError(false);
      setMetadataModalOpen(false);
    } catch (error: any) {
      console.error(error);
      setStatus(`Metadata Import Failed: ${error.message}`);
      setIsError(true);
    } finally {
      setIsImporting(false);
    }
  };

  // Helper to safely update settings state
  const updateLocalSetting = (key: string, value: string) => {
    setSettings((prev) => ({ ...prev, [key]: value }));
  };

  const handleExport = async (sectionId: string, url: string, filename: string) => {
    setExportingSectionId(sectionId);
    try {
      await downloadFile(url, filename);
    } finally {
      setExportingSectionId(null);
    }
  };

  const importSections = [
    {
      id: 'library',
      title: 'Data Management (CSV)',
      icon: <FileSpreadsheet className="h-4 w-4" />,
      description: 'Export your library to back up analysis data. Import to restore or migrate data (supports path tracking).',
      onExport: () => handleExport('library', settingsService.getExportUrl('library'), 'plumdeck_library.csv'),
      onFileSelect: (file: File) => handleAnalyze(file, 'library'),
      variant: 'outline' as const,
      exportLabel: 'Export Library to CSV',
      importLabel: 'Import / Restore from CSV',
      isExporting: exportingSectionId === 'library'
    },
    {
      id: 'metadata',
      title: 'Metadata Management (Lightweight CSV)',
      icon: <Globe className="h-4 w-4" />,
      description: 'Use this to bulk update track metadata (Title, Artist, Genre, Verified status) externally. This will NOT affect analysis data.',
      onExport: () => handleExport('metadata', settingsService.getExportUrl('metadata'), 'plumdeck_metadata.csv'),
      onFileSelect: (file: File) => handleAnalyze(file, 'metadata'),
      variant: 'secondary' as const,
      exportLabel: 'Export Metadata CSV',
      importLabel: 'Update Metadata from CSV',
      isExporting: exportingSectionId === 'metadata'
    }
  ];

  return (
    <div className="p-4 h-full overflow-y-auto">
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <SettingsIcon className="h-5 w-5" />
            Application Settings
          </CardTitle>
          <CardDescription>
            Manage local application configuration and library data.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-6">
          {/* Status Message Area */}
          {status && (
            <div
              className={`text-sm p-2 rounded mb-2 flex items-center gap-2 ${
                isError
                  ? "bg-destructive/10 text-destructive"
                  : "bg-green-100 text-green-700"
              }`}
            >
              {isError && <AlertCircle className="h-4 w-4" />}
              {status}
            </div>
          )}

          {/* Configuration Section */}
          <div className="space-y-4">
            <h3 className="text-sm font-medium text-muted-foreground">
              General Configuration
            </h3>

            <div className="space-y-2">
              <Label>録音の保存形式</Label>
              <Select
                value={settings.recording_format || "WAV"}
                onValueChange={(value) => void saveSetting("recording_format", value)}
              >
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {/* 実際に書き出せることを 1 形式ずつ録音して確認したものだけ。 */}
                  <SelectItem value="WAV">WAV（可逆・最大サイズ）</SelectItem>
                  <SelectItem value="AIFF">AIFF（可逆）</SelectItem>
                  <SelectItem value="FLAC">FLAC（可逆・圧縮）</SelectItem>
                  <SelectItem value="MP3">MP3（非可逆）</SelectItem>
                  <SelectItem value="OGG">OGG Vorbis（非可逆）</SelectItem>
                </SelectContent>
              </Select>
              <p className="text-xs text-muted-foreground">
                次の録音から反映されます。AAC はこのビルドのエンジンでは書き出せないため除いています。
              </p>
            </div>

            <div className="space-y-2">
              <Label htmlFor="recording-directory">録音の保存先</Label>
              <div className="flex gap-2">
                <Input
                  id="recording-directory"
                  value={settings.recording_directory ?? ""}
                  placeholder="未設定のときは ~/Music/plumdeck Recordings"
                  onChange={(event) =>
                    setSettings((prev) => ({ ...prev, recording_directory: event.target.value }))
                  }
                  onKeyDown={(event) => {
                    if (event.key === "Enter") {
                      event.preventDefault();
                      void saveSetting("recording_directory", (settings.recording_directory ?? "").trim());
                    }
                  }}
                />
                <Button
                  variant="secondary"
                  onClick={() =>
                    void saveSetting("recording_directory", (settings.recording_directory ?? "").trim())
                  }
                >
                  保存
                </Button>
              </div>
              <p className="text-xs text-muted-foreground">
                絶対パスで指定してください。保存すると次の録音から反映されます（エンジンの再起動は不要）。フォルダが無ければ自動で作成されます。
              </p>
            </div>

            <div className="space-y-2">
              <Label>Theme</Label>
              <Select value={theme} onValueChange={(val: any) => setTheme(val)}>
                <SelectTrigger>
                  <SelectValue placeholder="Select theme" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="light">Light</SelectItem>
                  <SelectItem value="dark">Dark</SelectItem>
                  <SelectItem value="system">System</SelectItem>
                </SelectContent>
              </Select>
            </div>

            <div className="space-y-2">
              <Label htmlFor="root_path">Default Root Path</Label>
              <div className="flex gap-2">
                <Input
                  id="root_path"
                  placeholder="/Users/username/Music"
                  value={settings["root_path"] || ""}
                  onChange={(e) =>
                    updateLocalSetting("root_path", e.target.value)
                  }
                />
                <Button
                  onClick={() =>
                    saveSetting("root_path", settings["root_path"] || "")
                  }
                >
                  Save
                </Button>
              </div>
            </div>

            <div className="space-y-2">
              <Label htmlFor="setlist_default_length">
                セットリスト自動生成のデフォルト曲数
              </Label>
              <div className="flex gap-2">
                <Input
                  id="setlist_default_length"
                  type="number"
                  min={1}
                  placeholder="10"
                  value={settings["setlist_default_length"] ?? ""}
                  onChange={(e) =>
                    updateLocalSetting(
                      "setlist_default_length",
                      e.target.value
                    )
                  }
                  className="w-32"
                />
                <Button
                  onClick={() =>
                    saveSetting(
                      "setlist_default_length",
                      settings["setlist_default_length"] || "10"
                    )
                  }
                >
                  Save
                </Button>
              </div>
              <p className="text-xs text-muted-foreground">
                MCP の generate_auto_setlist
                で曲数未指定時に使われるデフォルト曲数。
              </p>
            </div>
          </div>

          <Separator />

          {/* MCP-owned AI runtime */}
          <div className="space-y-4">
            <h3 className="text-sm font-medium text-muted-foreground flex items-center gap-2">
              <Bot className="h-4 w-4" />
              AI Runtime
            </h3>
            <div className="grid gap-2 p-4 border rounded-md bg-muted/20">
              <p className="text-sm font-medium">Provided by the connected MCP client</p>
              <p className="text-xs text-muted-foreground leading-relaxed">
                plumdeck does not store model names or API keys. Genre classification,
                natural-language vibe interpretation, and lyric wordplay reasoning use
                the model in Codex, Claude, or whichever MCP client is connected.
                Connection details and available tools are shown on the MCP page.
              </p>
            </div>
          </div>

          {importSections.map((section) => (
            <div key={section.id}>
              <Separator className="my-4" />
              <ImportSection {...section} />
            </div>
          ))}
        </CardContent>
      </Card>

      <LibraryImportDialog
        open={importModalOpen}
        onOpenChange={setImportModalOpen}
        analysis={analysisResult}
        isAnalyzing={isAnalyzing}
        isImporting={isImporting}
        onExecute={handleExecuteImport}
      />

      <MetadataImportDialog
        open={metadataModalOpen}
        onOpenChange={setMetadataModalOpen}
        analysis={metadataAnalysis}
        isAnalyzing={isAnalyzing}
        isImporting={isImporting}
        onExecute={handleExecuteMetadataImport}
      />
    </div>
  );
}
