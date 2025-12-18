import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Trash, Save } from "lucide-react";
import { Prompt } from "./types";

interface PromptEditorProps {
  isEditing: boolean;
  editForm: Partial<Prompt>;
  selectedPrompt: Prompt | null;
  onEditFormChange: (form: Partial<Prompt>) => void;
  onSave: () => void;
  onDelete: (id: number) => void;
}

export function PromptEditor({
  isEditing,
  editForm,
  selectedPrompt,
  onEditFormChange,
  onSave,
  onDelete,
}: PromptEditorProps) {
  if (!isEditing) {
    return (
      <div className="flex-1">
        <div className="h-full flex items-center justify-center text-muted-foreground border rounded-md border-dashed">
          Select a prompt to edit or create a new one.
        </div>
      </div>
    );
  }

  return (
    <div className="flex-1">
      <Card className="h-full flex flex-col">
        <CardHeader>
          <CardTitle>
            <Input
              value={editForm.name || ""}
              onChange={(e) =>
                onEditFormChange({ ...editForm, name: e.target.value })
              }
              placeholder="Prompt Name"
            />
          </CardTitle>
        </CardHeader>
        <CardContent className="flex-1 flex flex-col gap-4">
          <textarea
            className="flex-1 resize-none w-full p-2 border rounded-md bg-background"
            value={editForm.content || ""}
            onChange={(e) =>
              onEditFormChange({ ...editForm, content: e.target.value })
            }
            placeholder="Enter prompt content..."
          />
          <div className="flex justify-end gap-2">
            {selectedPrompt && (
              <Button
                variant="destructive"
                onClick={() => onDelete(selectedPrompt.id)}
              >
                <Trash className="h-4 w-4 mr-2" /> Delete
              </Button>
            )}
            <Button onClick={onSave}>
              <Save className="h-4 w-4 mr-2" /> Save
            </Button>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
