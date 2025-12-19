import { Loader2 } from "lucide-react";

export function LoadingScreen() {
  return (
    <div className="flex h-screen w-screen flex-col items-center justify-center bg-background text-foreground space-y-6">
      <div className="relative flex flex-col items-center">
        <div className="relative h-24 w-24 mb-6 flex items-center justify-center">
          <img 
            src="/DJALY_LOGO.png" 
            alt="Djaly Logo" 
            className="h-24 w-24 object-contain"
          />
        </div>
        
        <div className="flex flex-col items-center space-y-2">
          <div className="flex items-center space-x-2 text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" />
            <p className="text-sm font-medium">Initializing backend services...</p>
          </div>
        </div>
      </div>
    </div>
  );
}
