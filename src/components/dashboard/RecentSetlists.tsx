import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { ListMusic, Calendar, ChevronRight } from "lucide-react";
import { DashboardStats } from "@/services/system";
import { formatRelativeTime } from "@/lib/utils";

interface RecentSetlistsProps {
  setlists: DashboardStats["recent_setlists"];
  onNavigate: (view: string) => void;
}

export function RecentSetlists({ setlists, onNavigate }: RecentSetlistsProps) {
  return (
    <Card className="h-full flex flex-col">
      <CardHeader className="pb-3 border-b">
        <div className="flex items-center justify-between">
          <CardTitle className="text-lg font-medium">Recent Setlists</CardTitle>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => onNavigate("setlists")}
          >
            View All
          </Button>
        </div>
      </CardHeader>
      <CardContent className="p-0 flex-1 overflow-y-auto">
        {setlists.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-40 text-muted-foreground">
            <ListMusic className="h-8 w-8 mb-2 opacity-50" />
            <span className="text-sm">No setlists created yet.</span>
          </div>
        ) : (
          <div className="divide-y">
            {setlists.map((setlist) => (
              <div
                key={setlist.id}
                className="flex items-center justify-between p-4 hover:bg-muted/50 transition-colors cursor-pointer group"
                onClick={() => onNavigate("setlists")}
              >
                <div className="flex items-center gap-3">
                  <div className="bg-primary/10 p-2 rounded-full text-primary">
                    <ListMusic className="h-4 w-4" />
                  </div>
                  <div>
                    <div className="font-medium text-sm">{setlist.name}</div>
                    <div className="text-xs text-muted-foreground flex items-center gap-1">
                      <Calendar className="h-3 w-3" />
                      {formatRelativeTime(setlist.updated_at)}
                    </div>
                  </div>
                </div>
                <ChevronRight className="h-4 w-4 text-muted-foreground opacity-0 group-hover:opacity-100 transition-opacity" />
              </div>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
