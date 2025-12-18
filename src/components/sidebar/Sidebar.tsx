import {
  Music,
  Settings,
  FileText,
  Menu,
  Folder,
  List,
  Tags,
  LayoutDashboard,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { NavButton } from "./NavButton";

interface SidebarProps {
  activeView: string;
  onNavigate: (view: string) => void;
  isOpen: boolean;
  toggleSidebar: () => void;
}

export function Sidebar({
  activeView,
  onNavigate,
  isOpen,
  toggleSidebar,
}: SidebarProps) {
  return (
    <div
      className={cn(
        "flex flex-col border-r bg-background transition-all duration-300",
        isOpen ? "w-64" : "w-16"
      )}
    >
      <div className="p-4 flex items-center justify-between h-16 border-b">
        {isOpen && <span className="font-bold text-xl">Djaly</span>}
        <Button variant="ghost" size="icon" onClick={toggleSidebar}>
          <Menu className="h-5 w-5" />
        </Button>
      </div>

      <div className="flex-1 py-4 flex flex-col gap-2">
        <NavButton
          icon={<LayoutDashboard className="h-5 w-5" />}
          label="Dashboard"
          isActive={activeView === "dashboard"}
          onClick={() => onNavigate("dashboard")}
          isOpen={isOpen}
        />
        <NavButton
          icon={<Music className="h-5 w-5" />}
          label="Library"
          isActive={activeView === "library"}
          onClick={() => onNavigate("library")}
          isOpen={isOpen}
        />
        <NavButton
          icon={<List className="h-5 w-5" />}
          label="Setlists"
          isActive={activeView === "setlists"}
          onClick={() => onNavigate("setlists")}
          isOpen={isOpen}
        />
        <NavButton
          icon={<Folder className="h-5 w-5" />}
          label="Explorer"
          isActive={activeView === "explorer"}
          onClick={() => onNavigate("explorer")}
          isOpen={isOpen}
        />
        <NavButton
          icon={<Tags className="h-5 w-5" />}
          label="Genres"
          isActive={activeView === "genres"}
          onClick={() => onNavigate("genres")}
          isOpen={isOpen}
        />
        <NavButton
          icon={<FileText className="h-5 w-5" />}
          label="Prompts"
          isActive={activeView === "prompts"}
          onClick={() => onNavigate("prompts")}
          isOpen={isOpen}
        />
        <NavButton
          icon={<Settings className="h-5 w-5" />}
          label="Settings"
          isActive={activeView === "settings"}
          onClick={() => onNavigate("settings")}
          isOpen={isOpen}
        />
      </div>
    </div>
  );
}
