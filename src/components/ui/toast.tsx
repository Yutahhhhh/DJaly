import { useEffect, useState } from "react";
import { CheckCircle2, XCircle, Info, X } from "lucide-react";
import { cn } from "@/lib/utils";

/**
 * 外部依存なしの軽量トーストシステム。
 * どこからでも toast.success / toast.error / toast.info を呼び出せる。
 * <Toaster /> を App のルートに1つ配置すること。
 */

export type ToastType = "success" | "error" | "info";

export interface ToastItem {
  id: number;
  type: ToastType;
  title: string;
  description?: string;
}

type Listener = (items: ToastItem[]) => void;

let toastItems: ToastItem[] = [];
let listeners: Listener[] = [];
let nextId = 1;

function emit() {
  const snapshot = [...toastItems];
  listeners.forEach((l) => l(snapshot));
}

function dismiss(id: number) {
  toastItems = toastItems.filter((t) => t.id !== id);
  emit();
}

function push(type: ToastType, title: string, description?: string) {
  const id = nextId++;
  toastItems = [...toastItems, { id, type, title, description }];
  emit();

  // エラーは長め、それ以外は短めに自動消去
  const duration = type === "error" ? 7000 : 3500;
  setTimeout(() => dismiss(id), duration);
  return id;
}

export const toast = {
  success: (title: string, description?: string) => push("success", title, description),
  error: (title: string, description?: string) => push("error", title, description),
  info: (title: string, description?: string) => push("info", title, description),
  dismiss,
};

const ICONS: Record<ToastType, typeof Info> = {
  success: CheckCircle2,
  error: XCircle,
  info: Info,
};

export function Toaster() {
  const [items, setItems] = useState<ToastItem[]>([]);

  useEffect(() => {
    const listener: Listener = (next) => setItems(next);
    listeners.push(listener);
    return () => {
      listeners = listeners.filter((l) => l !== listener);
    };
  }, []);

  if (items.length === 0) return null;

  return (
    <div className="fixed bottom-4 right-4 z-[200] flex flex-col gap-2 w-80 pointer-events-none">
      {items.map((item) => {
        const Icon = ICONS[item.type];
        return (
          <div
            key={item.id}
            className={cn(
              "pointer-events-auto rounded-lg border bg-background shadow-lg p-3 flex items-start gap-2.5 animate-in slide-in-from-bottom-2 fade-in",
              item.type === "error" && "border-destructive/40",
              item.type === "success" && "border-green-500/40"
            )}
          >
            <Icon
              className={cn(
                "h-4 w-4 mt-0.5 shrink-0",
                item.type === "success" && "text-green-500",
                item.type === "error" && "text-destructive",
                item.type === "info" && "text-primary"
              )}
            />
            <div className="flex-1 min-w-0">
              <div className="text-sm font-semibold leading-tight">{item.title}</div>
              {item.description && (
                <div className="text-xs text-muted-foreground mt-1 break-words line-clamp-4">
                  {item.description}
                </div>
              )}
            </div>
            <button
              className="text-muted-foreground hover:text-foreground shrink-0"
              onClick={() => dismiss(item.id)}
            >
              <X className="h-3.5 w-3.5" />
            </button>
          </div>
        );
      })}
    </div>
  );
}
