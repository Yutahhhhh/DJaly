import { useState, useEffect } from "react";
import { Preset, Prompt } from "./types";
import { PresetList } from "./PresetList";
import { PresetEditor } from "./PresetEditor";
import { presetsService } from "@/services/presets";
import { promptsService } from "@/services/prompts";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { PromptList } from "./PromptList";
import { PromptEditor } from "./PromptEditor";

export function PromptManager() {
  const [mode, setMode] = useState("presets"); // 'presets' | 'prompts'

  // Presets State
  const [presets, setPresets] = useState<Preset[]>([]);
  const [selectedPreset, setSelectedPreset] = useState<Preset | null>(null);
  const [isEditingPreset, setIsEditingPreset] = useState(false);
  const [presetForm, setPresetForm] = useState<Partial<Preset>>({});

  // Prompts State (Shared)
  const [prompts, setPrompts] = useState<Prompt[]>([]);
  const [selectedPrompt, setSelectedPrompt] = useState<Prompt | null>(null);
  const [isEditingPrompt, setIsEditingPrompt] = useState(false);
  const [promptForm, setPromptForm] = useState<Partial<Prompt>>({});

  useEffect(() => {
    fetchData();
  }, []);

  const fetchData = async () => {
    try {
      const [pData, prData] = await Promise.all([
        presetsService.getAll(),
        promptsService.getAll(),
      ]);
      setPresets(pData);
      setPrompts(prData);
    } catch (e) {
      console.error("Failed to fetch data", e);
    }
  };

  // --- Preset Actions ---
  const handleCreatePreset = () => {
    setPresetForm({
      name: "New Preset",
      description: "",
      preset_type: "all",
      filters: {},
    });
    setSelectedPreset(null);
    setIsEditingPreset(true);
  };

  const handleSelectPreset = (preset: Preset) => {
    setSelectedPreset(preset);
    setPresetForm(preset);
    setIsEditingPreset(true);
  };

  const handleSavePreset = async () => {
    if (!presetForm.name) return;
    try {
      if (selectedPreset) {
        await presetsService.update(selectedPreset.id, presetForm);
      } else {
        await presetsService.create(presetForm);
      }
      fetchData();
      setIsEditingPreset(false);
      setSelectedPreset(null);
    } catch (e) {
      console.error(e);
    }
  };

  const handleDeletePreset = async (id: number) => {
    if (!confirm("Delete this preset?")) return;
    try {
      await presetsService.delete(id);
      fetchData();
      setSelectedPreset(null);
      setIsEditingPreset(false);
    } catch (e) {
      console.error(e);
    }
  };

  // --- Prompt Actions ---
  const handleCreatePrompt = () => {
    setPromptForm({ name: "New Prompt", content: "", is_default: false });
    setSelectedPrompt(null);
    setIsEditingPrompt(true);
  };

  const handleSelectPrompt = (prompt: Prompt) => {
    setSelectedPrompt(prompt);
    setPromptForm(prompt);
    setIsEditingPrompt(true);
  };

  const handleSavePrompt = async () => {
    if (!promptForm.name) return;
    try {
      if (selectedPrompt) {
        await promptsService.update(selectedPrompt.id, promptForm);
      } else {
        await promptsService.create(promptForm);
      }
      fetchData();
      setIsEditingPrompt(false);
      setSelectedPrompt(null);
    } catch (e) {
      console.error(e);
    }
  };

  const handleDeletePrompt = async (id: number) => {
    if (!confirm("Delete this prompt?")) return;
    try {
      await promptsService.delete(id);
      fetchData();
      setSelectedPrompt(null);
      setIsEditingPrompt(false);
    } catch (e) {
      console.error(e);
    }
  };

  return (
    <div className="h-full flex flex-col p-4 gap-4">
      <Tabs
        value={mode}
        onValueChange={setMode}
        className="w-full h-full flex flex-col"
      >
        <TabsList className="w-full justify-start">
          <TabsTrigger value="presets">Preset Manager (Main)</TabsTrigger>
          <TabsTrigger value="prompts">Raw Prompts</TabsTrigger>
        </TabsList>

        <TabsContent value="presets" className="flex-1 flex gap-6 mt-4 min-h-0">
          <PresetList
            presets={presets}
            selectedPresetId={selectedPreset?.id || null}
            onSelect={handleSelectPreset}
            onCreate={handleCreatePreset}
          />
          <PresetEditor
            isEditing={isEditingPreset}
            editForm={presetForm}
            prompts={prompts}
            onEditFormChange={setPresetForm}
            onSave={handleSavePreset}
            onDelete={handleDeletePreset}
            onCancel={() => setIsEditingPreset(false)}
          />
        </TabsContent>

        <TabsContent value="prompts" className="flex-1 flex gap-6 mt-4 min-h-0">
          <PromptList
            prompts={prompts}
            selectedPrompt={selectedPrompt}
            onSelect={handleSelectPrompt}
            onCreate={handleCreatePrompt}
          />
          <PromptEditor
            isEditing={isEditingPrompt}
            editForm={promptForm}
            selectedPrompt={selectedPrompt}
            onEditFormChange={setPromptForm}
            onSave={handleSavePrompt}
            onDelete={handleDeletePrompt}
          />
        </TabsContent>
      </Tabs>
    </div>
  );
}
