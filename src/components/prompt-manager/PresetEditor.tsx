import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Trash, Save } from "lucide-react";
import { Preset, Prompt } from "./types";

interface PresetEditorProps {
  isEditing: boolean;
  editForm: Partial<Preset>;
  prompts: Prompt[];
  onEditFormChange: (form: Partial<Preset>) => void;
  onSave: () => void;
  onDelete: (id: number) => void;
  onCancel: () => void;
}

export function PresetEditor({
  isEditing,
  editForm,
  prompts,
  onEditFormChange,
  onSave,
  onDelete,
  onCancel,
}: PresetEditorProps) {
  if (!isEditing) {
    return (
      <div className="flex-1">
        <div className="h-full flex items-center justify-center text-muted-foreground border rounded-md border-dashed bg-muted/10">
          Select a preset to edit or create a new one.
        </div>
      </div>
    );
  }

  return (
    <div className="flex-1 h-full overflow-hidden flex flex-col">
      <Card className="h-full flex flex-col border-0 shadow-none">
        <CardHeader className="border-b px-4 py-3">
          <CardTitle className="flex items-center gap-2">
            <Input
              value={editForm.name || ""}
              onChange={(e) =>
                onEditFormChange({ ...editForm, name: e.target.value })
              }
              placeholder="Preset Name"
              className="text-lg font-bold h-9"
            />
          </CardTitle>
        </CardHeader>
        <CardContent className="flex-1 flex flex-col gap-6 overflow-y-auto p-4">
          {/* Basic Info */}
          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-2">
              <label className="text-sm font-medium">Type</label>
              <Select
                value={editForm.preset_type || "all"}
                onValueChange={(val: any) =>
                  onEditFormChange({ ...editForm, preset_type: val })
                }
              >
                <SelectTrigger>
                  <SelectValue placeholder="Preset Type" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">All (Universal)</SelectItem>
                  <SelectItem value="search">Search Only</SelectItem>
                  <SelectItem value="generation">Generation Only</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <label className="text-sm font-medium">Linked Prompt</label>
              <Select
                value={editForm.prompt_id?.toString() || "none"}
                onValueChange={(val) =>
                  onEditFormChange({
                    ...editForm,
                    prompt_id: val === "none" ? undefined : parseInt(val),
                  })
                }
              >
                <SelectTrigger>
                  <SelectValue placeholder="Select a Prompt" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="none">-- No Prompt --</SelectItem>
                  {prompts.map((p) => (
                    <SelectItem key={p.id} value={p.id.toString()}>
                      {p.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>

          <div className="space-y-2">
            <label className="text-sm font-medium">Description</label>
            <Textarea
              value={editForm.description || ""}
              onChange={(e) =>
                onEditFormChange({ ...editForm, description: e.target.value })
              }
              placeholder="Describe what this preset does..."
              className="h-20 resize-none"
            />
          </div>
        </CardContent>
        <div className="p-4 border-t flex justify-between bg-muted/10">
          <Button
            variant="destructive"
            size="sm"
            onClick={() => editForm.id && onDelete(editForm.id)}
            disabled={!editForm.id}
          >
            <Trash className="h-4 w-4 mr-2" />
            Delete
          </Button>
          <div className="flex gap-2">
            <Button variant="outline" size="sm" onClick={onCancel}>
              Cancel
            </Button>
            <Button size="sm" onClick={onSave}>
              <Save className="h-4 w-4 mr-2" />
              Save Changes
            </Button>
          </div>
        </div>
      </Card>
    </div>
  );
}
