import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

interface NavButtonProps {
  icon: React.ReactNode;
  label: string;
  isActive: boolean;
  onClick: () => void;
  isOpen: boolean;
}

export function NavButton({ icon, label, isActive, onClick, isOpen }: NavButtonProps) {
  return (
    <Button
      variant={isActive ? "secondary" : "ghost"}
      className={cn(
        "w-full justify-start gap-4 px-4",
        !isOpen && "justify-center px-2"
      )}
      onClick={onClick}
    >
      {icon}
      {isOpen && <span>{label}</span>}
    </Button>
  );
}
