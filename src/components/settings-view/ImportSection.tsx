import { Button } from "@/components/ui/button";
import { Download, Upload, Loader2 } from "lucide-react";
import { useRef } from "react";

interface ImportSectionProps {
  title: string;
  description: string;
  onExport: () => void;
  onFileSelect: (file: File) => void;
  exportLabel?: string;
  importLabel?: string;
  icon?: React.ReactNode;
  variant?: "default" | "destructive" | "outline" | "secondary" | "ghost" | "link";
  isExporting?: boolean;
}

export function ImportSection({
  title,
  description,
  onExport,
  onFileSelect,
  exportLabel = "Export CSV",
  importLabel = "Import CSV",
  icon,
  variant = "outline",
  isExporting = false,
}: ImportSectionProps) {
  const fileInputRef = useRef<HTMLInputElement>(null);

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) {
      onFileSelect(file);
    }
    if (fileInputRef.current) {
      fileInputRef.current.value = "";
    }
  };

  return (
    <div className="space-y-4">
      <h3 className="text-sm font-medium text-muted-foreground flex items-center gap-2">
        {icon}
        {title}
      </h3>
      <div className="flex flex-col sm:flex-row gap-4">
        <Button 
          variant={variant} 
          onClick={onExport} 
          className="flex-1 gap-2"
          disabled={isExporting}
        >
          {isExporting ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <Download className="h-4 w-4" />
          )}
          {exportLabel}
        </Button>

        <div className="flex-1">
          <input
            type="file"
            accept=".csv"
            className="hidden"
            ref={fileInputRef}
            onChange={handleFileChange}
          />
          <Button
            variant={variant}
            className="w-full gap-2"
            onClick={() => fileInputRef.current?.click()}
          >
            <Upload className="h-4 w-4" />
            {importLabel}
          </Button>
        </div>
      </div>
      <p className="text-xs text-muted-foreground">{description}</p>
    </div>
  );
}
