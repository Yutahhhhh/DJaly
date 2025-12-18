import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Plus, ListMusic, MoreVertical, Trash2, Edit2, Download, Loader2 } from "lucide-react";
import { Setlist, setlistsService } from "@/services/setlists";
import { downloadFile } from "@/lib/download";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";

interface SetlistSidebarProps {
  setlists: Setlist[];
  activeSetlistId: number | null;
  onSelect: (id: number) => void;
  onCreate: (name: string) => void;
  onUpdateName: (id: number, name: string) => void;
  onDelete: (id: number) => void;
}

export function SetlistSidebar({
  setlists,
  activeSetlistId,
  onSelect,
  onCreate,
  onUpdateName,
  onDelete,
}: SetlistSidebarProps) {
  const [editingId, setEditingId] = useState<number | null>(null);
  const [editName, setEditName] = useState("");
  const [exportingId, setExportingId] = useState<number | null>(null);

  const startEdit = (setlist: Setlist) => {
    setEditingId(setlist.id);
    setEditName(setlist.name);
  };

  const submitEdit = () => {
    if (editingId) {
      onUpdateName(editingId, editName);
      setEditingId(null);
    }
  };

  const handleExport = async (setlist: Setlist) => {
    setExportingId(setlist.id);
    try {
      const url = setlistsService.getExportUrl(setlist.id);
      const filename = `${setlist.name.replace(/[\\/*?:"<>|]/g, "")}.m3u8`;
      await downloadFile(url, filename);
    } finally {
      setExportingId(null);
    }
  };

  return (
    <div className="w-64 border-r flex flex-col bg-background">
      <div className="p-4 border-b flex items-center justify-between">
        <h3 className="font-semibold flex items-center gap-2">
          <ListMusic className="h-5 w-5" /> Setlists
        </h3>
        <Button
          size="sm"
          variant="ghost"
          onClick={() => onCreate("New Setlist")}
        >
          <Plus className="h-4 w-4" />
        </Button>
      </div>
      <ScrollArea className="flex-1">
        <div className="p-2 space-y-1">
          {setlists.map((setlist) => (
            <div
              key={setlist.id}
              className={`group flex items-center justify-between p-2 rounded-md cursor-pointer transition-colors ${
                activeSetlistId === setlist.id
                  ? "bg-secondary text-secondary-foreground"
                  : "hover:bg-muted"
              }`}
              onClick={() => onSelect(setlist.id)}
              onDoubleClick={() => startEdit(setlist)}
            >
              {editingId === setlist.id ? (
                <Input
                  value={editName}
                  onChange={(e) => setEditName(e.target.value)}
                  onBlur={submitEdit}
                  onKeyDown={(e) => e.key === "Enter" && submitEdit()}
                  autoFocus
                  className="h-7 text-sm"
                />
              ) : (
                <span className="text-sm font-medium truncate flex-1">
                  {setlist.name}
                </span>
              )}

              {exportingId === setlist.id ? (
                <div className="h-6 w-6 flex items-center justify-center">
                  <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
                </div>
              ) : (
                <DropdownMenu>
                  <DropdownMenuTrigger asChild>
                    <Button
                      variant="ghost"
                      size="icon"
                      className="h-6 w-6 opacity-0 group-hover:opacity-100"
                    >
                      <MoreVertical className="h-3 w-3" />
                    </Button>
                  </DropdownMenuTrigger>
                  <DropdownMenuContent align="end">
                    <DropdownMenuItem onClick={() => startEdit(setlist)}>
                      <Edit2 className="h-3 w-3 mr-2" /> Rename
                    </DropdownMenuItem>

                    <DropdownMenuItem onClick={() => handleExport(setlist)}>
                      <Download className="h-3 w-3 mr-2" /> Export (.m3u8)
                    </DropdownMenuItem>

                    <DropdownMenuSeparator />

                    <DropdownMenuItem
                      className="text-destructive"
                      onClick={(e) => {
                        e.stopPropagation();
                        onDelete(setlist.id);
                      }}
                    >
                      <Trash2 className="h-3 w-3 mr-2" /> Delete
                    </DropdownMenuItem>
                  </DropdownMenuContent>
                </DropdownMenu>
              )}
            </div>
          ))}
        </div>
      </ScrollArea>
    </div>
  );
}
