import { Button } from "@/components/ui/button";
import { ChevronRight } from "lucide-react";

interface BreadcrumbsProps {
  currentPath: string;
  onNavigate: (path: string) => void;
}

export function Breadcrumbs({ currentPath, onNavigate }: BreadcrumbsProps) {
  const getBreadcrumbs = () => {
    if (!currentPath) return [];
    const parts = currentPath.split("/").filter(Boolean);
    const crumbs = [];
    let accum = "";

    if (currentPath.startsWith("/")) {
      crumbs.push({ name: "/", path: "/" });
      accum = "/";
    }

    parts.forEach((part) => {
      const nextPath = accum === "/" ? `/${part}` : `${accum}/${part}`;
      crumbs.push({ name: part, path: nextPath });
      accum = nextPath;
    });
    return crumbs;
  };

  const breadcrumbs = getBreadcrumbs();

  return (
    <div className="flex items-center gap-1 text-sm text-muted-foreground overflow-x-auto whitespace-nowrap pb-2 flex-1 mr-4">
      {breadcrumbs.map((crumb, index) => (
        <div key={crumb.path} className="flex items-center">
          <Button
            variant="ghost"
            size="sm"
            className="h-6 px-2"
            onClick={() => onNavigate(crumb.path)}
          >
            {crumb.name}
          </Button>
          {index < breadcrumbs.length - 1 && (
            <ChevronRight className="h-4 w-4" />
          )}
        </div>
      ))}
    </div>
  );
}
