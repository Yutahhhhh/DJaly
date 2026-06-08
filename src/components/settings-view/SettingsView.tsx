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
  Check,
  FileSpreadsheet,
  Cpu,
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
  PresetAnalysisResult 
} from "@/services/settings";
import { ImportSection } from "./ImportSection";
import { LibraryImportDialog } from "./LibraryImportDialog";
import { MetadataImportDialog } from "./MetadataImportDialog";
import { PresetImportDialog } from "./PresetImportDialog";
import { useTheme } from "@/components/theme-provider";
import { downloadFile } from "@/lib/download";

const MODEL_PRESETS: Record<
  string,
  { value: string; label: string; note: string }[]
> = {
  ollama: [
    {
      value: "llama3.2",
      label: "llama3.2 - Local default",
      note: "ローカルで完結させたい場合の標準候補です。",
    },
    {
      value: "qwen2.5:7b",
      label: "qwen2.5:7b - Structured output",
      note: "インストール済みなら、短いJSON出力系のタスクで安定しやすい候補です。",
    },
  ],
  openai: [
    {
      value: "gpt-5.4-mini",
      label: "gpt-5.4-mini - Recommended for Djaly",
      note: "ジャンル分析、歌詞キーワード抽出、vibeのJSON化に対して品質と速度のバランスが良い候補です。",
    },
    {
      value: "gpt-5.5",
      label: "gpt-5.5 - Highest quality",
      note: "速度やコストより精度を優先したい場合の高品質候補です。",
    },
    {
      value: "gpt-5.4-nano",
      label: "gpt-5.4-nano - Low cost",
      note: "大量のシンプルな分類を低コストで回したい場合に向いています。",
    },
  ],
  codex: [
    {
      value: "gpt-5.5",
      label: "gpt-5.5 - Codex CLI 推奨",
      note: "ローカルのCodex CLIにログイン済みのChatGPTサブスク認証を使います。APIキーは不要です。",
    },
    {
      value: "gpt-5.4-mini",
      label: "gpt-5.4-mini - 軽量",
      note: "Codex CLI経由で、速度を優先したい場合の候補です。",
    },
    {
      value: "codex-mini-latest",
      label: "codex-mini-latest - 実験用",
      note: "Codex CLI向けの実験候補です。利用できない場合は別モデルを選んでください。",
    },
  ],
  anthropic: [
    {
      value: "claude-sonnet-4-20250514",
      label: "claude-sonnet-4 - Recommended Claude",
      note: "微妙なジャンル/サブジャンル判断と、きれいな構造化レスポンスに向いたClaude候補です。",
    },
    {
      value: "claude-3-5-haiku-20241022",
      label: "claude-3.5-haiku - Fast/low cost",
      note: "シンプルな一括分類を速く低コストで回したい場合に向いています。",
    },
    {
      value: "claude-opus-4-20250514",
      label: "claude-opus-4 - Highest quality",
      note: "難しいメタデータ判断で、コストより品質を優先したい場合の候補です。",
    },
  ],
  google: [
    {
      value: "gemini-1.5-flash",
      label: "gemini-1.5-flash - Fast default",
      note: "素早い分類や抽出に使いやすい標準候補です。",
    },
    {
      value: "gemini-flash-latest",
      label: "gemini-flash-latest - Latest Flash alias",
      note: "Googleの高速モデルの最新エイリアスを使いたい場合の候補です。",
    },
  ],
};

const PROVIDER_KEY_LABELS: Record<string, string> = {
  openai: "OpenAI API Key",
  anthropic: "Anthropic API Key",
  google: "Google API Key",
};

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
  
  // Preset Import State
  const [presetModalOpen, setPresetModalOpen] = useState(false);
  const [presetAnalysis, setPresetAnalysis] = useState<PresetAnalysisResult | null>(null);

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

  // 一括保存
  const saveAllSettings = async () => {
    setStatus("Saving all settings...");
    setIsError(false);
    try {
      for (const [key, value] of Object.entries(settings)) {
        await settingsService.save(key, value);
      }
      setStatus("All settings saved.");
      setTimeout(() => setStatus(""), 2000);
    } catch (e: any) {
      console.error("Failed to save settings", e);
      setStatus(`Error: ${e.message}`);
      setIsError(true);
    }
  };

  const handleAnalyze = async (file: File, type: 'library' | 'metadata' | 'presets') => {
    setIsAnalyzing(true);
    if (type === 'library') { setImportModalOpen(true); setAnalysisResult(null); }
    if (type === 'metadata') { setMetadataModalOpen(true); setMetadataAnalysis(null); }
    if (type === 'presets') { setPresetModalOpen(true); setPresetAnalysis(null); }

    try {
      const result = await settingsService.analyzeImport(file, type);
      if (type === 'library') setAnalysisResult(result as LibraryAnalysisResult);
      if (type === 'metadata') setMetadataAnalysis(result as MetadataAnalysisResult);
      if (type === 'presets') setPresetAnalysis(result as PresetAnalysisResult);
    } catch (error: any) {
      console.error(error);
      if (type === 'library') setImportModalOpen(false);
      if (type === 'metadata') setMetadataModalOpen(false);
      if (type === 'presets') setPresetModalOpen(false);
      
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

  const handleExecutePresetImport = async () => {
    if (!presetAnalysis) return;
    setIsImporting(true);

    try {
      const payload = {
        new_presets: presetAnalysis.new_presets,
        updates: presetAnalysis.updates,
      };

      const data = await settingsService.executeImport(payload, 'presets');

      setStatus(data.message);
      setIsError(false);
      setPresetModalOpen(false);
    } catch (error: any) {
      console.error(error);
      setStatus(`Preset Import Failed: ${error.message}`);
      setIsError(true);
    } finally {
      setIsImporting(false);
    }
  };

  // Helper to safely update settings state
  const updateLocalSetting = (key: string, value: string) => {
    setSettings((prev) => ({ ...prev, [key]: value }));
  };

  const getDefaultModel = (provider: string) => {
    switch (provider) {
      case "ollama": return "llama3.2";
      case "openai": return "gpt-5.4-mini";
      case "codex": return "gpt-5.5";
      case "anthropic": return "claude-sonnet-4-20250514";
      case "google": return "gemini-flash-latest";
      default: return "";
    }
  };

  const handleProviderChange = (newProvider: string) => {
    setSettings((prev) => {
      // Try to find a saved model for this provider, otherwise use default
      const savedModel = prev[`${newProvider}_model`];
      const nextModel = savedModel || getDefaultModel(newProvider);
      
      return {
        ...prev,
        llm_provider: newProvider,
        llm_model: nextModel
      };
    });
  };

  const handleModelNameChange = (newModel: string) => {
    setSettings((prev) => {
      const provider = prev["llm_provider"] || "ollama";
      return {
        ...prev,
        llm_model: newModel,
        [`${provider}_model`]: newModel // Save specifically for this provider
      };
    });
  };

  const handleExport = async (sectionId: string, url: string, filename: string) => {
    setExportingSectionId(sectionId);
    try {
      await downloadFile(url, filename);
    } finally {
      setExportingSectionId(null);
    }
  };

  const currentProvider = settings["llm_provider"] || "ollama";
  const currentModelPresets = MODEL_PRESETS[currentProvider] || [];
  const currentModel = settings["llm_model"] || "";
  const selectedPreset = currentModelPresets.find(
    (preset) => preset.value === currentModel
  );
  const apiKeySettingKey =
    `${currentProvider}_api_key`;
  const requiresApiKey = ["openai", "anthropic", "google"].includes(
    currentProvider
  );

  const importSections = [
    {
      id: 'library',
      title: 'Data Management (CSV)',
      icon: <FileSpreadsheet className="h-4 w-4" />,
      description: 'Export your library to back up analysis data. Import to restore or migrate data (supports path tracking).',
      onExport: () => handleExport('library', settingsService.getExportUrl('library'), 'djaly_library.csv'),
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
      onExport: () => handleExport('metadata', settingsService.getExportUrl('metadata'), 'djaly_metadata.csv'),
      onFileSelect: (file: File) => handleAnalyze(file, 'metadata'),
      variant: 'secondary' as const,
      exportLabel: 'Export Metadata CSV',
      importLabel: 'Update Metadata from CSV',
      isExporting: exportingSectionId === 'metadata'
    },
    {
      id: 'presets',
      title: 'Preset Management (CSV)',
      icon: <FileSpreadsheet className="h-4 w-4" />,
      description: 'Backup and restore your generation presets and prompts.',
      onExport: () => handleExport('presets', settingsService.getExportUrl('presets'), 'djaly_presets.csv'),
      onFileSelect: (file: File) => handleAnalyze(file, 'presets'),
      variant: 'outline' as const,
      exportLabel: 'Export Presets CSV',
      importLabel: 'Import Presets from CSV',
      isExporting: exportingSectionId === 'presets'
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
            Manage your application configuration and AI connections.
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
          </div>

          <Separator />

          {/* AI Settings Section */}
          <div className="space-y-4">
            <h3 className="text-sm font-medium text-muted-foreground flex items-center gap-2">
              <Cpu className="h-4 w-4" />
              AI & LLM Configuration
            </h3>

            <div className="grid gap-4 p-4 border rounded-md bg-muted/20">
              <div className="space-y-2">
                <Label htmlFor="llm_provider">AI Provider</Label>
                <Select
                  value={currentProvider}
                  onValueChange={handleProviderChange}
                >
                  <SelectTrigger className="bg-background">
                    <SelectValue placeholder="Select Provider" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="ollama">Ollama (Local)</SelectItem>
                    <SelectItem value="openai">OpenAI (GPT)</SelectItem>
                    <SelectItem value="codex">
                      Codex CLI (ChatGPT Subscription)
                    </SelectItem>
                    <SelectItem value="anthropic">
                      Anthropic (Claude)
                    </SelectItem>
                    <SelectItem value="google">Google (Gemini)</SelectItem>
                  </SelectContent>
                </Select>
              </div>

              {currentModelPresets.length > 0 && (
                <div className="space-y-2">
                  <Label htmlFor="model_preset">Recommended Model</Label>
                  <Select
                    value={selectedPreset ? selectedPreset.value : "__custom__"}
                    onValueChange={(value) => {
                      if (value !== "__custom__") {
                        handleModelNameChange(value);
                      }
                    }}
                  >
                    <SelectTrigger className="bg-background">
                      <SelectValue placeholder="Select recommended model" />
                    </SelectTrigger>
                    <SelectContent>
                      {currentModelPresets.map((preset) => (
                        <SelectItem key={preset.value} value={preset.value}>
                          {preset.label}
                        </SelectItem>
                      ))}
                      <SelectItem value="__custom__">Custom model</SelectItem>
                    </SelectContent>
                  </Select>
                  <p className="text-xs text-muted-foreground">
                    {selectedPreset?.note ||
                      "下の入力欄で任意のモデルIDを指定できます。"}
                  </p>
                </div>
              )}

              <div className="space-y-2">
                <Label htmlFor="llm_model">Model Name</Label>
                <Input
                  id="llm_model"
                  placeholder={getDefaultModel(currentProvider)}
                  value={settings["llm_model"] || ""}
                  onChange={(e) => handleModelNameChange(e.target.value)}
                  className="bg-background"
                />
                <p className="text-xs text-muted-foreground">
                  Djaly mainly uses this for genre/subgenre analysis, lyric
                  keyword extraction, and vibe-to-JSON parameter generation.
                </p>
              </div>

              {/* Provider specific inputs */}
              {currentProvider === "ollama" ? (
                <div className="space-y-2 animate-in fade-in">
                  <Label htmlFor="ollama_host">Ollama Host URL</Label>
                  <Input
                    id="ollama_host"
                    placeholder="http://localhost:11434"
                    value={settings["ollama_host"] || ""}
                    onChange={(e) =>
                      updateLocalSetting("ollama_host", e.target.value)
                    }
                    className="bg-background"
                  />
                  <div className="text-xs text-muted-foreground">
                    <div>
                      Please install Ollama and run it in the background
                    </div>
                    <code>Default: http://localhost:11434</code>
                  </div>
                </div>
              ) : currentProvider === "codex" ? (
                <div className="space-y-3 animate-in fade-in">
                  <div className="space-y-2">
                    <Label htmlFor="codex_cli_path">Codex CLI Path</Label>
                    <Input
                      id="codex_cli_path"
                      placeholder="codex または /opt/homebrew/bin/codex"
                      value={settings["codex_cli_path"] || ""}
                      onChange={(e) =>
                        updateLocalSetting("codex_cli_path", e.target.value)
                      }
                      className="bg-background"
                    />
                    <p className="text-xs text-muted-foreground">
                      空欄の場合はPATH、/opt/homebrew/bin/codex、/usr/local/bin/codex の順に探します。
                    </p>
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="codex_timeout_seconds">
                      Codex Timeout Seconds
                    </Label>
                    <Input
                      id="codex_timeout_seconds"
                      inputMode="numeric"
                      placeholder="180"
                      value={settings["codex_timeout_seconds"] || ""}
                      onChange={(e) =>
                        updateLocalSetting(
                          "codex_timeout_seconds",
                          e.target.value
                        )
                      }
                      className="bg-background"
                    />
                    <p className="text-xs text-muted-foreground">
                      Codex CLIにログイン済みのChatGPTサブスク認証を使います。APIキーは不要です。
                    </p>
                  </div>
                </div>
              ) : requiresApiKey ? (
                <div className="space-y-2 animate-in fade-in">
                  <Label htmlFor="api_key">
                    {PROVIDER_KEY_LABELS[currentProvider] || "API Key"}
                  </Label>
                  <Input
                    id="api_key"
                    type="password"
                    placeholder={`sk-...`}
                    value={settings[apiKeySettingKey] || ""}
                    onChange={(e) =>
                      updateLocalSetting(
                        apiKeySettingKey,
                        e.target.value
                      )
                    }
                    className="bg-background"
                  />
                </div>
              ) : null}

              <Button onClick={saveAllSettings} className="w-full mt-2">
                <Check className="mr-2 h-4 w-4" /> Save AI Settings
              </Button>
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

      <PresetImportDialog
        open={presetModalOpen}
        onOpenChange={setPresetModalOpen}
        analysis={presetAnalysis}
        isAnalyzing={isAnalyzing}
        isImporting={isImporting}
        onExecute={handleExecutePresetImport}
      />
    </div>
  );
}
